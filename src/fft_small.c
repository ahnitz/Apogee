/* peakfft: back end for N = 2^12 .. 2^16.
 *
 * These sizes are L2-resident, so there is no memory-traffic pressure to trade
 * accuracy against: the intermediate stays fp32 and nothing is quantised.  The
 * split is balanced (N1, N2 ~ sqrt(N)) and BOTH stages are element-space
 * transforms batched across 16 lanes, so neither needs in-register shuffles.
 *
 * The only corner turn is fused into stage A's store: 16 consecutive k2 columns
 * are transposed in registers so the write to the intermediate is a contiguous
 * 64-byte run rather than a 16-way scatter.
 *
 *   n = n2*N1 + n1          (n1 contiguous)
 *   stage A: for each n1, DFT over n2 (size N2); lanes = 16 consecutive n1
 *   twiddle W_N[n1*k2]; intermediate held as inter[n1][k2]
 *   stage B: for each k2, DFT over n1 (size N1); lanes = 16 consecutive k2
 *   output X[k1*N2 + k2], contiguous in k2
 */
#define _GNU_SOURCE
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <immintrin.h>
#include "peakfft.h"
#include "internal.h"
#include "transpose16.h"

struct PS {
  size_t N; int N1,N2;
  float *ire,*iim;                  /* intermediate, SoA, [n1][k2] */
  __m512 *bR,*bI,*sR,*sI;           /* element buffers + scratch */
  __m512 *TLr,*TLi;                 /* [N2] lanes l: W_N[l*k2] */
  float *w1r,*w1i,*w2r,*w2i;        /* W_N1[], W_N2[] for elem_fft_generic */
  float *hr,*hi,*lr,*li;            /* 2-level table for W_{N/16}[g*k2] */
  unsigned nmask;                   /* N/16 - 1 */
};

PS *pfs_create(size_t N){
  int m=0; while(((size_t)1<<m)<N) m++;
  int n1=1<<((m+1)/2), n2=1<<(m/2);          /* N1 >= N2, both >= 16 */
  PS *p=aligned_alloc(64,sizeof(PS)); if(!p) return NULL;
  memset(p,0,sizeof(PS));
  p->N=N; p->N1=n1; p->N2=n2; p->nmask=(unsigned)(N/16-1);
  size_t maxe = (size_t)(n1>n2?n1:n2);
  p->ire=aligned_alloc(64,N*4);  p->iim=aligned_alloc(64,N*4);
  p->bR =aligned_alloc(64,maxe*64); p->bI=aligned_alloc(64,maxe*64);
  p->sR =aligned_alloc(64,maxe*64); p->sI=aligned_alloc(64,maxe*64);
  p->TLr=aligned_alloc(64,(size_t)n2*64); p->TLi=aligned_alloc(64,(size_t)n2*64);
  for(int k2=0;k2<n2;k2++){
    float tr[16],ti[16];
    for(int l=0;l<16;l++){ double a=-2.0*M_PI*(double)l*k2/(double)N;
      tr[l]=(float)cos(a); ti[l]=(float)sin(a); }
    p->TLr[k2]=_mm512_loadu_ps(tr); p->TLi[k2]=_mm512_loadu_ps(ti);
  }
  p->w1r=aligned_alloc(64,(size_t)n1*4); p->w1i=aligned_alloc(64,(size_t)n1*4);
  p->w2r=aligned_alloc(64,(size_t)n2*4); p->w2i=aligned_alloc(64,(size_t)n2*4);
  for(int j=0;j<n1;j++){ double a=-2.0*M_PI*j/n1; p->w1r[j]=(float)cos(a); p->w1i[j]=(float)sin(a); }
  for(int j=0;j<n2;j++){ double a=-2.0*M_PI*j/n2; p->w2r[j]=(float)cos(a); p->w2i[j]=(float)sin(a); }
  { size_t nhi=(N/16)/256; if(nhi<1) nhi=1; double Nq=(double)(N/16);
    p->hr=aligned_alloc(64,nhi*4+64); p->hi=aligned_alloc(64,nhi*4+64);
    p->lr=aligned_alloc(64,256*4);    p->li=aligned_alloc(64,256*4);
    for(size_t j=0;j<nhi;j++){ double a=-2.0*M_PI*(double)(j*256)/Nq;
      p->hr[j]=(float)cos(a); p->hi[j]=(float)sin(a); }
    for(int j=0;j<256;j++){ double b=-2.0*M_PI*(double)j/Nq;
      p->lr[j]=(float)cos(b); p->li[j]=(float)sin(b); }
  }
  return p;
}

void pfs_destroy(PS*p){
  if(!p) return;
  free(p->ire); free(p->iim); free(p->bR); free(p->bI); free(p->sR); free(p->sI);
  free(p->TLr); free(p->TLi); free(p->w1r); free(p->w1i); free(p->w2r); free(p->w2i);
  free(p->hr); free(p->hi); free(p->lr); free(p->li); free(p);
}

static void stageA(PS*p,const float*in,int conj){
  const int N1=p->N1,N2=p->N2;
  const __m512i ev=_mm512_setr_epi32(0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30);
  const __m512i od=_mm512_setr_epi32(1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31);
  const __m512 sg=conj?_mm512_castsi512_ps(_mm512_set1_epi32((int)0x80000000)):_mm512_setzero_ps();
  __m512 TR[16],TI[16],OR[16],OI[16];
  for(int g=0;g<N1/16;g++){
    const float*src=in+2*(16*g);
    for(int n2=0;n2<N2;n2++){
      __m512 a=_mm512_loadu_ps(src+(size_t)n2*2*N1), b=_mm512_loadu_ps(src+(size_t)n2*2*N1+16);
      p->bR[n2]=_mm512_permutex2var_ps(a,ev,b);
      p->bI[n2]=_mm512_xor_ps(_mm512_permutex2var_ps(a,od,b),sg);
    }
    __m512 *RR=p->bR,*RI=p->bI;
    if(elem_fft_generic(N2,p->bR,p->bI,p->sR,p->sI,p->w2r,p->w2i)){ RR=p->sR; RI=p->sI; }
    for(int b=0;b<N2/16;b++){
      for(int t=0;t<16;t++){
        int k2=16*b+t;
        unsigned mm=((unsigned)g*(unsigned)k2)&p->nmask, m1=mm>>8, m0=mm&255;
        float sr=p->hr[m1]*p->lr[m0]-p->hi[m1]*p->li[m0];
        float si=p->hr[m1]*p->li[m0]+p->hi[m1]*p->lr[m0];
        __m512 SR=_mm512_set1_ps(sr),SI=_mm512_set1_ps(si);
        __m512 tr=_mm512_fmsub_ps(SR,p->TLr[k2],_mm512_mul_ps(SI,p->TLi[k2]));
        __m512 ti=_mm512_fmadd_ps(SR,p->TLi[k2],_mm512_mul_ps(SI,p->TLr[k2]));
        __m512 xr=RR[k2],xi=RI[k2];
        TR[t]=_mm512_fmsub_ps(xr,tr,_mm512_mul_ps(xi,ti));
        TI[t]=_mm512_fmadd_ps(xr,ti,_mm512_mul_ps(xi,tr));
      }
      t16(TR,OR); t16(TI,OI);      /* lanes become k2, element index becomes n1 */
      for(int i=0;i<16;i++){
        size_t off=(size_t)(16*g+i)*N2+16*b;
        _mm512_storeu_ps(p->ire+off,OR[i]);
        _mm512_storeu_ps(p->iim+off,OI[i]);
      }
    }
  }
}

/* stage B for one block of 16 columns; leaves the result in *RR/*RI (elements = k1) */
static void stageB(PS*p,int b,__m512**RR,__m512**RI){
  const int N1=p->N1,N2=p->N2;
  for(int n1=0;n1<N1;n1++){
    size_t off=(size_t)n1*N2+16*b;
    p->bR[n1]=_mm512_loadu_ps(p->ire+off);
    p->bI[n1]=_mm512_loadu_ps(p->iim+off);
  }
  *RR=p->bR; *RI=p->bI;
  if(elem_fft_generic(N1,p->bR,p->bI,p->sR,p->sI,p->w1r,p->w1i)){ *RR=p->sR; *RI=p->sI; }
}

void pfs_exact(PS*p,const float*in,float*out,int conj){
  const int N1=p->N1,N2=p->N2;
  const __m512i lo=_mm512_setr_epi32(0,16,1,17,2,18,3,19,4,20,5,21,6,22,7,23);
  const __m512i hi=_mm512_setr_epi32(8,24,9,25,10,26,11,27,12,28,13,29,14,30,15,31);
  const __m512 sg=conj?_mm512_castsi512_ps(_mm512_set1_epi32((int)0x80000000)):_mm512_setzero_ps();
  stageA(p,in,conj);
  for(int b=0;b<N2/16;b++){
    __m512 *RR,*RI; stageB(p,b,&RR,&RI);
    for(int k1=0;k1<N1;k1++){
      float*d=out+2*((size_t)k1*N2+16*b);
      __m512 vi=_mm512_xor_ps(RI[k1],sg);
      _mm512_storeu_ps(d,   _mm512_permutex2var_ps(RR[k1],lo,vi));
      _mm512_storeu_ps(d+16,_mm512_permutex2var_ps(RR[k1],hi,vi));
    }
  }
}

int pfs_topk(PS*p,const float*in,int K,pf_peak*out,int conj){
  const int N1=p->N1,N2=p->N2;
  stageA(p,in,conj);
  pf_cand T[PF_MAX_K]; int n=0; float thr=-1.f;
  __m512 vthr=_mm512_set1_ps(thr);
  float br[16],bi[16],bm[16];
  for(int b=0;b<N2/16;b++){
    __m512 *RR,*RI; stageB(p,b,&RR,&RI);
    for(int k1=0;k1<N1;k1++){
      __m512 m2=_mm512_fmadd_ps(RR[k1],RR[k1],_mm512_mul_ps(RI[k1],RI[k1]));
      __mmask16 msk=_mm512_cmp_ps_mask(m2,vthr,_CMP_GT_OQ);
      if(msk){
        _mm512_storeu_ps(bm,m2); _mm512_storeu_ps(br,RR[k1]); _mm512_storeu_ps(bi,RI[k1]);
        while(msk){
          int l=__builtin_ctz((unsigned)msk); msk&=(__mmask16)(msk-1);
          if(bm[l]<=thr) continue;
          pf_push(T,K,&n,bm[l],(int)((size_t)k1*N2+16*b+l),br[l],bi[l]);
          if(n==K){ thr=T[0].mag2; vthr=_mm512_set1_ps(thr); }
        }
      }
    }
  }
  for(int a=1;a<n;a++){ pf_cand v=T[a]; int c=a-1;
    while(c>=0&&T[c].mag2<v.mag2){T[c+1]=T[c];c--;} T[c+1]=v; }
  for(int a=0;a<n;a++){ out[a].index=T[a].idx; out[a].re=T[a].re;
    out[a].im=conj?-T[a].im:T[a].im; out[a].magnitude=sqrtf(T[a].mag2); }
  return n;
}
