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
#ifdef PF_PROF
#include <time.h>
double pf_pA=0,pf_pB=0,pf_pAfft=0,pf_pAtw=0,pf_pAq=0,pf_pBload=0,pf_pBfft=0,pf_pBscan=0;
static inline double pnow(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+1e-9*t.tv_nsec;}
#define PT(x) double x=pnow()
#define PACC(v,x) v+=pnow()-(x)
#else
#define PT(x)
#define PACC(v,x)
#endif
#include "codelets.h"
#include "elemfft.h"

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
  /* Intermediate as 24-bit block floating point rather than fp32: a 16-bit plane
     the screening pass reads, plus an 8-bit residual touched only for the columns
     that actually hold a peak.  Cuts the intermediate round trip from 16 bytes per
     complex to 10, which is what decides the large sizes once the working set
     leaves L2.  Layout keeps re and im adjacent so each store is a full line. */
  short *q;            /* [2*(n1*N2 + W*b) + l] = re, +W = im */
  signed char *r8;     /* same indexing, low 8 bits                */
  float *scl;          /* [n1*(N2/W) + b] dequant scale            */
  float *ire,*iim;     /* fp32 intermediate, used when quantising would not pay */
  int useq;            /* 1 = quantised 24-bit, 0 = plain fp32                  */
  vf *bR,*bI,*sR,*sI;
  vf *TLr,*TLi;
  float *w1r,*w1i,*w2r,*w2i;
  float *hr,*hi,*lr,*li;
  float *scg;          /* [g][k2] scalar part of the stage-A twiddle, precomputed */
  vf *twr,*twi;        /* full twiddle vectors, when they are small enough to hold */
  int fulltw;
  unsigned nmask;
  int a1,a2,b1,b2;      /* codelet factorisation of N1 and N2 */
  emap ea,eb;           /* index maps for those factorisations */
} BP;

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
  efactor(n1,&p->a1,&p->a2); efactor(n2,&p->b1,&p->b2);
  p->ea=emake(p->a1,p->a2); p->eb=emake(p->b1,p->b2);
  int a1,a2,b1,b2; efactor(n1,&a1,&a2); efactor(n2,&b1,&b2);
  size_t s1=(a2==1)?(size_t)n1:(size_t)ESTRIDE(a1)*a2;
  size_t s2=(b2==1)?(size_t)n2:(size_t)ESTRIDE(b1)*b2;
  size_t me=s1>s2?s1:s2;
  /* Quantising trades arithmetic for bytes moved.  That is only a win once the
     intermediate stops fitting in cache - below that it is pure added work, and it
     measured ~1.9x slower at 2^12.  L2 here is 1 MiB, so switch at 2^17. */
  p->useq = (N*8 > (1u<<20));
  if(p->useq){
    p->q  =aligned_alloc(64,N*2*sizeof(short));
    p->r8 =aligned_alloc(64,N*2);
    p->scl=aligned_alloc(64,(size_t)n1*(n2/PF_W)*sizeof(float)+64);
  } else {
    p->ire=aligned_alloc(64,N*sizeof(float));
    p->iim=aligned_alloc(64,N*sizeof(float));
  }
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
  { int a1,a2; efactor(n1,&a1,&a2);
    for(int k=0;k<(a2==1?1:a2);k++) for(int e=0;e<a1;e++){
      double a=-2.0*M_PI*(double)e*k/n1;
      p->w1r[(size_t)k*a1+e]=(float)cos(a); p->w1i[(size_t)k*a1+e]=(float)sin(a); } }
  { int b1,b2; efactor(n2,&b1,&b2);
    for(int k=0;k<(b2==1?1:b2);k++) for(int e=0;e<b1;e++){
      double a=-2.0*M_PI*(double)e*k/n2;
      p->w2r[(size_t)k*b1+e]=(float)cos(a); p->w2i[(size_t)k*b1+e]=(float)sin(a); } }
  /* The stage-A twiddle used to be rebuilt per element from a two-level table:
     four scalar multiplies and a broadcast, all on the critical path, for ~22% of
     all instructions at small N.  Precompute instead.  The full vector form is
     8N bytes, which is worth it while it stays small; above that keep just the
     scalar part (8N/W bytes) so the large sizes do not pay extra traffic. */
  { size_t g_n=(size_t)n1/PF_W;
    p->scg=aligned_alloc(64,g_n*(size_t)n2*2*sizeof(float)+64);
    p->fulltw = (N<= (1u<<16));
    if(p->fulltw){
      p->twr=aligned_alloc(64,g_n*(size_t)n2*sizeof(vf));
      p->twi=aligned_alloc(64,g_n*(size_t)n2*sizeof(vf));
    }
  }
  { size_t nhi=(N/PF_W)/256; if(nhi<1) nhi=1; double Nq=(double)(N/PF_W);
    p->hr=aligned_alloc(64,nhi*4+64); p->hi=aligned_alloc(64,nhi*4+64);
    p->lr=aligned_alloc(64,256*4);    p->li=aligned_alloc(64,256*4);
    for(size_t j=0;j<nhi;j++){ double a=-2.0*M_PI*(double)(j*256)/Nq;
      p->hr[j]=(float)cos(a); p->hi[j]=(float)sin(a); }
    for(int j=0;j<256;j++){ double b=-2.0*M_PI*(double)j/Nq;
      p->lr[j]=(float)cos(b); p->li[j]=(float)sin(b); }
  }
  /* fill the precomputed twiddles */
  { unsigned nmask=(unsigned)(N/PF_W-1);
    for(int g=0; g<n1/PF_W; g++) for(int k2=0;k2<n2;k2++){
      unsigned mm=((unsigned)g*(unsigned)k2)&nmask, m1=mm>>8, m0=mm&255;
      float sr=p->hr[m1]*p->lr[m0]-p->hi[m1]*p->li[m0];
      float si=p->hr[m1]*p->li[m0]+p->hi[m1]*p->lr[m0];
      size_t idx=(size_t)g*n2+k2;
      p->scg[2*idx]=sr; p->scg[2*idx+1]=si;
      if(p->fulltw){
        vf SR=V_SET1(sr),SI=V_SET1(si);
        p->twr[idx]=V_FMSUB(SR,p->TLr[k2],V_MUL(SI,p->TLi[k2]));
        p->twi[idx]=V_FMADD(SR,p->TLi[k2],V_MUL(SI,p->TLr[k2]));
      }
    }
  }
  return p;
}

void FN(destroy)(void *vp){
  BP *p=vp; if(!p) return;
  free(p->q);free(p->r8);free(p->scl);free(p->ire);free(p->iim);free(p->bR);free(p->bI);free(p->sR);free(p->sI);
  free(p->TLr);free(p->TLi);free(p->w1r);free(p->w1i);free(p->w2r);free(p->w2i);
  free(p->hr);free(p->hi);free(p->lr);free(p->li);
  free(p->scg);free(p->twr);free(p->twi);free(p);
}

static void stageA(BP*p,const float*in,int conj){
  const int N1=p->N1,N2=p->N2;
  const vf sg = conj?V_SIGNMASK():V_ZERO();
  vf TR[PF_W],TI[PF_W],OR[PF_W],OI[PF_W];
  for(int g=0;g<N1/PF_W;g++){
    const float*src=in+2*(PF_W*g);
    for(int n2=0;n2<N2;n2++){
      vf r,i; v_deint(src+(size_t)n2*2*N1,&r,&i);
      int q=einp(&p->eb,n2);
      p->bR[q]=r; p->bI[q]=V_XOR(i,sg);
    }
    efft(N2,p->bR,p->bI,p->sR,p->sI,p->w2r,p->w2i);
    vf *RR=p->bR,*RI=p->bI;
    for(int b=0;b<N2/PF_W;b++){
      if(p->fulltw){
        const vf *twr=p->twr+(size_t)g*N2+PF_W*b, *twi=p->twi+(size_t)g*N2+PF_W*b;
        for(int t=0;t<PF_W;t++){
          int eb=eidx(&p->eb,PF_W*b+t);
          vf xr=RR[eb],xi=RI[eb];
          TR[t]=V_FMSUB(xr,twr[t],V_MUL(xi,twi[t]));
          TI[t]=V_FMADD(xr,twi[t],V_MUL(xi,twr[t]));
        }
      } else {
        const float *sc=p->scg+2*((size_t)g*N2+PF_W*b);
        for(int t=0;t<PF_W;t++){
          int k2=PF_W*b+t;
          vf SR=V_SET1(sc[2*t]),SI=V_SET1(sc[2*t+1]);
          vf tr=V_FMSUB(SR,p->TLr[k2],V_MUL(SI,p->TLi[k2]));
          vf ti=V_FMADD(SR,p->TLi[k2],V_MUL(SI,p->TLr[k2]));
          int eb=eidx(&p->eb,k2);
          vf xr=RR[eb],xi=RI[eb];
          TR[t]=V_FMSUB(xr,tr,V_MUL(xi,ti));
          TI[t]=V_FMADD(xr,ti,V_MUL(xi,tr));
        }
      }
      V_TRANSPOSE(TR,OR); V_TRANSPOSE(TI,OI);
      /* One block-floating-point scale for the whole W x W tile, not one per row.
         The horizontal reduce and the divide were costing more than either FFT
         stage; sharing them over the tile makes them W times rarer.  A tile max is
         a little larger than a row max, so the quantiser is marginally coarser -
         24 bits leaves plenty of margin for that. */
      if(!p->useq){
        for(int i=0;i<PF_W;i++){
          size_t off=(size_t)(PF_W*g+i)*N2+PF_W*b;
          V_STOREU(p->ire+off,OR[i]); V_STOREU(p->iim+off,OI[i]);
        }
        continue;
      }
      vf amax=V_MAX(V_ABS(OR[0]),V_ABS(OI[0]));
      for(int i=1;i<PF_W;i++) amax=V_MAX(amax,V_MAX(V_ABS(OR[i]),V_ABS(OI[i])));
      float mx=v_reduce_max(amax);
      float sc = mx>0.f ? 8388607.0f/mx : 1.f;
      float dq = mx>0.f ? mx*(1.0f/8388607.0f) : 1.f;
      vf vs=V_SET1(sc);
      const vi CMAX=VI_SET1(8388607), CMIN=VI_SET1(-8388607);
      for(int i=0;i<PF_W;i++){
        int n1=PF_W*g+i;
        p->scl[(size_t)n1*(N2/PF_W)+b]=dq;
        vi xr=VI_MAX(CMIN,VI_MIN(CMAX,VI_CVT(V_MUL(OR[i],vs))));
        vi xi=VI_MAX(CMIN,VI_MIN(CMAX,VI_CVT(V_MUL(OI[i],vs))));
        size_t base=2*((size_t)n1*N2+PF_W*b);
        VI_STORE16(p->q+base,        VI_PACK16(VI_SRAI(xr,8)));
        VI_STORE16(p->q+base+PF_W,   VI_PACK16(VI_SRAI(xi,8)));
        VI_STORE8 (p->r8+base,       VI_PACK8(VI_AND(xr,VI_SET1(255))));
        VI_STORE8 (p->r8+base+PF_W,  VI_PACK8(VI_AND(xi,VI_SET1(255))));
      }

    }
  }
}

static void stageB(BP*p,int b,vf**RR,vf**RI,int exact){
  const int N1=p->N1,N2=p->N2; PT(_tb0);
  if(!p->useq){
    for(int n1=0;n1<N1;n1++){
      size_t off=(size_t)n1*N2+PF_W*b;
      int q=einp(&p->ea,n1);
      p->bR[q]=V_LOADU(p->ire+off); p->bI[q]=V_LOADU(p->iim+off);
    }
    PACC(pf_pBload,_tb0);
    PT(_tb2); efft(N1,p->bR,p->bI,p->sR,p->sI,p->w1r,p->w1i); PACC(pf_pBfft,_tb2);
    *RR=p->bR; *RI=p->bI;
    return;
  }
  for(int n1=0;n1<N1;n1++){
    size_t base=2*((size_t)n1*N2+PF_W*b);
    float s=p->scl[(size_t)n1*(N2/PF_W)+b];
    int q=einp(&p->ea,n1);
    vi hr=VI_UNPACK16(VI_LOAD16(p->q+base));
    vi hi=VI_UNPACK16(VI_LOAD16(p->q+base+PF_W));
    if(exact){
      vi lr=VI_UNPACKU8(VI_LOAD8(p->r8+base));
      vi li=VI_UNPACKU8(VI_LOAD8(p->r8+base+PF_W));
      vf vs=V_SET1(s);
      p->bR[q]=V_MUL(VI_CVTF(VI_OR(VI_SLLI(hr,8),lr)),vs);
      p->bI[q]=V_MUL(VI_CVTF(VI_OR(VI_SLLI(hi,8),li)),vs);
    } else {
      vf vs=V_SET1(s*256.0f);
      p->bR[q]=V_MUL(VI_CVTF(hr),vs);
      p->bI[q]=V_MUL(VI_CVTF(hi),vs);
    }
  }
  PACC(pf_pBload,_tb0);
  PT(_tb1); efft(N1,p->bR,p->bI,p->sR,p->sI,p->w1r,p->w1i); PACC(pf_pBfft,_tb1);
  *RR=p->bR; *RI=p->bI;
}

void FN(fft)(void *vp,const float*in,float*out,int conj){
  BP *p=vp; const int N1=p->N1,N2=p->N2;
  const vf sg = conj?V_SIGNMASK():V_ZERO();
  stageA(p,in,conj);
  for(int b=0;b<N2/PF_W;b++){
    vf *RR,*RI; stageB(p,b,&RR,&RI,1);
    for(int k1=0;k1<N1;k1++){ int e=eidx(&p->ea,k1);
      v_inter(out+2*((size_t)k1*N2+PF_W*b),RR[e],V_XOR(RI[e],sg)); }
  }
}

int FN(topk)(void *vp,const float*in,int K,pf_peak*out,int conj,size_t ws,size_t we){
  BP *p=vp; const int N1=p->N1,N2=p->N2;
  PT(_ta); stageA(p,in,conj); PACC(pf_pA,_ta);
  /* Screening is only 16-bit accurate, so the K-th and (K+1)-th candidate can be
     mis-ordered by it.  Keep a wider pool, refine all of it at 24 bits, then rank -
     otherwise a peak can be cut before it is ever looked at properly. */
  const int KP = p->useq ? ((K*2+8 > 256) ? 256 : K*2+8) : K;
  cand T[256]; int n=0; float thr=-1.f;
  vf vthr=V_SET1(thr);
  float br[PF_W],bi[PF_W],bm[PF_W];
  const unsigned allm=(PF_W==16)?0xFFFFu:0xFFu;
  for(int b=0;b<N2/PF_W;b++){
    /* outputs of this column block are k = k1*N2 + PF_W*b + l, so the window
       restricts k1 to a contiguous range; everything outside it is skipped
       without ever computing a magnitude. */
    long base=(long)PF_W*b;
    long lo=((long)ws-base-(PF_W-1)+N2-1)/N2, hi=((long)we-1-base)/N2;
    if(lo<0) lo=0;
    if(hi>N1-1) hi=N1-1;
    if(lo>hi) continue;
    vf *RR,*RI; stageB(p,b,&RR,&RI,0);
    for(long k1=lo;k1<=hi;k1++){
      int e=eidx(&p->ea,(int)k1);
      long k0=k1*N2+base;                     /* index of lane 0 */
      unsigned inw=allm;
      if(k0<(long)ws || k0+PF_W>(long)we){    /* partial block: mask the edges */
        inw=0;
        for(int l=0;l<PF_W;l++){ long k=k0+l;
          if(k>=(long)ws && k<(long)we) inw|=1u<<l; }
        if(!inw) continue;
      }
      vf m2=V_FMADD(RR[e],RR[e],V_MUL(RI[e],RI[e]));
      unsigned msk=V_GT_MASK(m2,vthr) & inw;
      if(msk){
        V_STOREU(bm,m2); V_STOREU(br,RR[e]); V_STOREU(bi,RI[e]);
        while(msk){
          int l=__builtin_ctz(msk); msk&=msk-1u;
          if(bm[l]<=thr) continue;
          push(T,KP,&n,bm[l],k0+l,br[l],bi[l]);
          if(n==KP){ thr=T[0].mag2; vthr=V_SET1(thr); }
        }
      }
    }
  }
  /* Screening ran on 16 bits; redo just the column blocks that produced a
     candidate at the full 24 bits so the reported values are exact. */
  for(int a=0; p->useq && a<n; a++){
    int bb=(int)((T[a].idx % N2) / PF_W), done=0;
    for(int c=0;c<a;c++) if((int)((T[c].idx % N2)/PF_W)==bb){ done=1; break; }
    if(done) continue;
    vf *RR,*RI; stageB(p,bb,&RR,&RI,1);
    for(int c=a;c<n;c++) if((int)((T[c].idx % N2)/PF_W)==bb){
      long k1=T[c].idx/N2; int l=(int)(T[c].idx%N2)-PF_W*bb;
      int e=eidx(&p->ea,(int)k1);
      float rr2[PF_W],ii2[PF_W];
      V_STOREU(rr2,RR[e]); V_STOREU(ii2,RI[e]);
      T[c].re=rr2[l]; T[c].im=ii2[l]; T[c].mag2=rr2[l]*rr2[l]+ii2[l]*ii2[l];
    }
  }
  for(int a=1;a<n;a++){ cand v=T[a]; int c=a-1;
    while(c>=0&&T[c].mag2<v.mag2){T[c+1]=T[c];c--;} T[c+1]=v; }
  int nout = n<K?n:K;
  for(int a=0;a<nout;a++){ out[a].index=T[a].idx; out[a].re=T[a].re;
    out[a].im=conj?-T[a].im:T[a].im; out[a].magnitude=sqrtf(T[a].mag2); }
  return nout;
}

const pf_backend CAT(pf_be_bal,PF_W) = {
#if PF_W==16
  "balanced-avx512",
#else
  "avx2",
#endif
  FN(create), FN(destroy), FN(fft), FN(topk), FN(supported)
};
