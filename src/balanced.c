/* peakfft: width-generic balanced-split back end.
 *
 * Compiled twice - once at PF_W=16 (AVX-512) and once at PF_W=8 (AVX2) - from the
 * same source, via the operation macros in simd.h.  This is the whole AVX2
 * implementation, and on AVX-512 it doubles as a cross-check of the specialised
 * paths.
 *
 *   N = N1 * N2 with both ~ sqrt(N) and both a multiple of the vector width.
 *   n = n2*N1 + n1                      (n1 contiguous)
 *   stage A: for each n1, DFT over n2 (size N2); lanes = W consecutive n1
 *   twiddle W_N[n1*k2]; intermediate held as inter[n1][k2], fp32
 *   stage B: for each k2, DFT over n1 (size N1); lanes = W consecutive k2
 *   output X[k1*N2 + k2], contiguous in k2
 *
 * Neither stage needs in-register shuffles: the lanes are independent transforms,
 * so every twiddle is a broadcast.  The single corner turn is fused into stage A's
 * store, where a W x W register transpose turns what would be a W-way scatter into
 * one contiguous run.
 */
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "simd.h"
#include "peakfft.h"
#include "backend.h"

#define CAT2(a,b) a##b
#define CAT(a,b) CAT2(a,b)
#define FN(name) CAT(CAT(pfb,PF_W),_##name)

typedef struct { float mag2; long idx; float re,im; } cand;
static void push(cand *T,int K,int *n,float m2,long idx,float vr,float vi){
  if(*n<K){ int i=(*n)++; T[i].mag2=m2; T[i].idx=idx; T[i].re=vr; T[i].im=vi;
    while(i>0&&T[i].mag2<T[(i-1)/2].mag2){ cand t=T[i];T[i]=T[(i-1)/2];T[(i-1)/2]=t; i=(i-1)/2; }
    return; }
  if(m2<=T[0].mag2) return;
  T[0].mag2=m2; T[0].idx=idx; T[0].re=vr; T[0].im=vi;
  for(int i=0;;){ int l=2*i+1,r=l+1,s=i;
    if(l<K&&T[l].mag2<T[s].mag2) s=l;
    if(r<K&&T[r].mag2<T[s].mag2) s=r;
    if(s==i) break;
    { cand t=T[i];T[i]=T[s];T[s]=t; } i=s; }
}

typedef struct {
  size_t N; int N1,N2;
  float *ire,*iim;
  vf *bR,*bI,*sR,*sI;
  vf *TLr,*TLi;
  float *w1r,*w1i,*w2r,*w2i;
  float *hr,*hi,*lr,*li;
  unsigned nmask;
} BP;

/* element-space Stockham FFT of size M; lanes are independent transforms */
static int efft(int M,vf*Xr,vf*Xi,vf*Yr,vf*Yi,const float*wr,const float*wi){
  const vf Z=V_ZERO();
  int n=M,s=1,flip=0;
  while(n>1){
    int r=(n%4==0)?4:2, m=n/r;
    for(int j=0;j<m;j++) for(int q=0;q<s;q++){
      int i0=q+s*j;
      if(r==4){
        int i1=i0+s*m,i2=i1+s*m,i3=i2+s*m;
        vf a0r=Xr[i0],a0i=Xi[i0],a1r=Xr[i1],a1i=Xi[i1];
        vf a2r=Xr[i2],a2i=Xi[i2],a3r=Xr[i3],a3i=Xi[i3];
        vf t0r=V_ADD(a0r,a2r),t0i=V_ADD(a0i,a2i);
        vf t1r=V_SUB(a0r,a2r),t1i=V_SUB(a0i,a2i);
        vf t2r=V_ADD(a1r,a3r),t2i=V_ADD(a1i,a3i);
        vf dr =V_SUB(a1r,a3r),di =V_SUB(a1i,a3i);
        vf t3r=di,t3i=V_SUB(Z,dr);
        vf o[4][2]={{V_ADD(t0r,t2r),V_ADD(t0i,t2i)},{V_ADD(t1r,t3r),V_ADD(t1i,t3i)},
                    {V_SUB(t0r,t2r),V_SUB(t0i,t2i)},{V_SUB(t1r,t3r),V_SUB(t1i,t3i)}};
        int o0=q+s*4*j, b=(j*s)&(M-1);
        Yr[o0]=o[0][0]; Yi[o0]=o[0][1];
        for(int l=1;l<4;l++){
          int bb=(l*b)&(M-1);
          vf cr=V_SET1(wr[bb]),ci=V_SET1(wi[bb]);
          Yr[o0+l*s]=V_FMSUB(o[l][0],cr,V_MUL(o[l][1],ci));
          Yi[o0+l*s]=V_FMADD(o[l][0],ci,V_MUL(o[l][1],cr));
        }
      } else {
        int i1=i0+s*m, o0=q+s*2*j, b=(j*s)&(M-1);
        vf a0r=Xr[i0],a0i=Xi[i0],a1r=Xr[i1],a1i=Xi[i1];
        Yr[o0]=V_ADD(a0r,a1r); Yi[o0]=V_ADD(a0i,a1i);
        vf dr=V_SUB(a0r,a1r),di=V_SUB(a0i,a1i);
        vf cr=V_SET1(wr[b]),ci=V_SET1(wi[b]);
        Yr[o0+s]=V_FMSUB(dr,cr,V_MUL(di,ci));
        Yi[o0+s]=V_FMADD(dr,ci,V_MUL(di,cr));
      }
    }
    { vf*t; t=Xr;Xr=Yr;Yr=t; t=Xi;Xi=Yi;Yi=t; }
    flip^=1; n=m; s*=r;
  }
  return flip;
}

int FN(supported)(size_t N){
  /* Kept identical to the AVX-512 back end so the supported set does not depend
     on which ISA happens to be selected: 1024, then 2^12..2^20. */
  if(N==1024u) return 1;
  if((N&(N-1))||N<4096u||N>(1u<<20)) return 0;
  int m=0; while(((size_t)1<<m)<N) m++;
  int n1=1<<((m+1)/2), n2=1<<(m/2);
  return n1>=PF_W && n2>=PF_W;
}

void *FN(create)(size_t N){
  if(!FN(supported)(N)) return NULL;
  int m=0; while(((size_t)1<<m)<N) m++;
  int n1=1<<((m+1)/2), n2=1<<(m/2);
  BP *p=aligned_alloc(64,sizeof(BP)); if(!p) return NULL;
  memset(p,0,sizeof(BP));
  p->N=N; p->N1=n1; p->N2=n2; p->nmask=(unsigned)(N/PF_W-1);
  size_t me=(size_t)(n1>n2?n1:n2);
  p->ire=aligned_alloc(64,N*4); p->iim=aligned_alloc(64,N*4);
  p->bR=aligned_alloc(64,me*sizeof(vf)); p->bI=aligned_alloc(64,me*sizeof(vf));
  p->sR=aligned_alloc(64,me*sizeof(vf)); p->sI=aligned_alloc(64,me*sizeof(vf));
  p->TLr=aligned_alloc(64,(size_t)n2*sizeof(vf)); p->TLi=aligned_alloc(64,(size_t)n2*sizeof(vf));
  for(int k2=0;k2<n2;k2++){
    float tr[PF_W],ti[PF_W];
    for(int l=0;l<PF_W;l++){ double a=-2.0*M_PI*(double)l*k2/(double)N;
      tr[l]=(float)cos(a); ti[l]=(float)sin(a); }
    p->TLr[k2]=V_LOADU(tr); p->TLi[k2]=V_LOADU(ti);
  }
  p->w1r=aligned_alloc(64,(size_t)n1*4); p->w1i=aligned_alloc(64,(size_t)n1*4);
  p->w2r=aligned_alloc(64,(size_t)n2*4); p->w2i=aligned_alloc(64,(size_t)n2*4);
  for(int j=0;j<n1;j++){ double a=-2.0*M_PI*j/n1; p->w1r[j]=(float)cos(a); p->w1i[j]=(float)sin(a); }
  for(int j=0;j<n2;j++){ double a=-2.0*M_PI*j/n2; p->w2r[j]=(float)cos(a); p->w2i[j]=(float)sin(a); }
  { size_t nhi=(N/PF_W)/256; if(nhi<1) nhi=1; double Nq=(double)(N/PF_W);
    p->hr=aligned_alloc(64,nhi*4+64); p->hi=aligned_alloc(64,nhi*4+64);
    p->lr=aligned_alloc(64,256*4);    p->li=aligned_alloc(64,256*4);
    for(size_t j=0;j<nhi;j++){ double a=-2.0*M_PI*(double)(j*256)/Nq;
      p->hr[j]=(float)cos(a); p->hi[j]=(float)sin(a); }
    for(int j=0;j<256;j++){ double b=-2.0*M_PI*(double)j/Nq;
      p->lr[j]=(float)cos(b); p->li[j]=(float)sin(b); }
  }
  return p;
}

void FN(destroy)(void *vp){
  BP *p=vp; if(!p) return;
  free(p->ire);free(p->iim);free(p->bR);free(p->bI);free(p->sR);free(p->sI);
  free(p->TLr);free(p->TLi);free(p->w1r);free(p->w1i);free(p->w2r);free(p->w2i);
  free(p->hr);free(p->hi);free(p->lr);free(p->li);free(p);
}

static void stageA(BP*p,const float*in,int conj){
  const int N1=p->N1,N2=p->N2;
  const vf sg = conj?V_SIGNMASK():V_ZERO();
  vf TR[PF_W],TI[PF_W],OR[PF_W],OI[PF_W];
  for(int g=0;g<N1/PF_W;g++){
    const float*src=in+2*(PF_W*g);
    for(int n2=0;n2<N2;n2++){
      vf r,i; v_deint(src+(size_t)n2*2*N1,&r,&i);
      p->bR[n2]=r; p->bI[n2]=V_XOR(i,sg);
    }
    vf *RR=p->bR,*RI=p->bI;
    if(efft(N2,p->bR,p->bI,p->sR,p->sI,p->w2r,p->w2i)){ RR=p->sR; RI=p->sI; }
    for(int b=0;b<N2/PF_W;b++){
      for(int t=0;t<PF_W;t++){
        int k2=PF_W*b+t;
        unsigned mm=((unsigned)g*(unsigned)k2)&p->nmask, m1=mm>>8, m0=mm&255;
        float sr=p->hr[m1]*p->lr[m0]-p->hi[m1]*p->li[m0];
        float si=p->hr[m1]*p->li[m0]+p->hi[m1]*p->lr[m0];
        vf SR=V_SET1(sr),SI=V_SET1(si);
        vf tr=V_FMSUB(SR,p->TLr[k2],V_MUL(SI,p->TLi[k2]));
        vf ti=V_FMADD(SR,p->TLi[k2],V_MUL(SI,p->TLr[k2]));
        vf xr=RR[k2],xi=RI[k2];
        TR[t]=V_FMSUB(xr,tr,V_MUL(xi,ti));
        TI[t]=V_FMADD(xr,ti,V_MUL(xi,tr));
      }
      V_TRANSPOSE(TR,OR); V_TRANSPOSE(TI,OI);
      for(int i=0;i<PF_W;i++){
        size_t off=(size_t)(PF_W*g+i)*N2+PF_W*b;
        V_STOREU(p->ire+off,OR[i]); V_STOREU(p->iim+off,OI[i]);
      }
    }
  }
}

static void stageB(BP*p,int b,vf**RR,vf**RI){
  const int N1=p->N1,N2=p->N2;
  for(int n1=0;n1<N1;n1++){
    size_t off=(size_t)n1*N2+PF_W*b;
    p->bR[n1]=V_LOADU(p->ire+off); p->bI[n1]=V_LOADU(p->iim+off);
  }
  *RR=p->bR; *RI=p->bI;
  if(efft(N1,p->bR,p->bI,p->sR,p->sI,p->w1r,p->w1i)){ *RR=p->sR; *RI=p->sI; }
}

void FN(fft)(void *vp,const float*in,float*out,int conj){
  BP *p=vp; const int N1=p->N1,N2=p->N2;
  const vf sg = conj?V_SIGNMASK():V_ZERO();
  stageA(p,in,conj);
  for(int b=0;b<N2/PF_W;b++){
    vf *RR,*RI; stageB(p,b,&RR,&RI);
    for(int k1=0;k1<N1;k1++)
      v_inter(out+2*((size_t)k1*N2+PF_W*b),RR[k1],V_XOR(RI[k1],sg));
  }
}

int FN(topk)(void *vp,const float*in,int K,pf_peak*out,int conj){
  BP *p=vp; const int N1=p->N1,N2=p->N2;
  stageA(p,in,conj);
  cand T[PF_MAX_K]; int n=0; float thr=-1.f;
  vf vthr=V_SET1(thr);
  float br[PF_W],bi[PF_W],bm[PF_W];
  for(int b=0;b<N2/PF_W;b++){
    vf *RR,*RI; stageB(p,b,&RR,&RI);
    for(int k1=0;k1<N1;k1++){
      vf m2=V_FMADD(RR[k1],RR[k1],V_MUL(RI[k1],RI[k1]));
      unsigned msk=V_GT_MASK(m2,vthr);
      if(msk){
        V_STOREU(bm,m2); V_STOREU(br,RR[k1]); V_STOREU(bi,RI[k1]);
        while(msk){
          int l=__builtin_ctz(msk); msk&=msk-1u;
          if(bm[l]<=thr) continue;
          push(T,K,&n,bm[l],(long)k1*N2+PF_W*b+l,br[l],bi[l]);
          if(n==K){ thr=T[0].mag2; vthr=V_SET1(thr); }
        }
      }
    }
  }
  for(int a=1;a<n;a++){ cand v=T[a]; int c=a-1;
    while(c>=0&&T[c].mag2<v.mag2){T[c+1]=T[c];c--;} T[c+1]=v; }
  for(int a=0;a<n;a++){ out[a].index=T[a].idx; out[a].re=T[a].re;
    out[a].im=conj?-T[a].im:T[a].im; out[a].magnitude=sqrtf(T[a].mag2); }
  return n;
}

const pf_backend CAT(pf_be_bal,PF_W) = {
#if PF_W==16
  "balanced-avx512",
#else
  "avx2",
#endif
  FN(create), FN(destroy), FN(fft), FN(topk), FN(supported)
};
