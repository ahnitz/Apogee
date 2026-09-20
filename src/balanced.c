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
#include "codelets.h"

#define CAT2(a,b) a##b
#define CAT(a,b) CAT2(a,b)
#define FN(name) CAT(CAT(pfb,PF_W),_##name)

/* factor M into two codelet-sized halves; M1 == M means "single codelet" */
static inline void efactor(int M,int *M1,int *M2){
  switch(M){
    case 1024: *M1=32; *M2=32; break;
    case  512: *M1=32; *M2=16; break;
    case  256: *M1=16; *M2=16; break;
    case  128: *M1=16; *M2=8;  break;
    default:   *M1=M;  *M2=1;  break;     /* 8,16,32,64 */
  }
}
#define ESTRIDE(M1) ((M1)+1)
/* Index maps between natural element order and the padded four-step layout.
   M1/M2 are powers of two, so these must be shifts and masks - a runtime integer
   divide here costs more than the transform stage it indexes into. */
typedef struct { int st, m2mask, m2shift, m1mask, m1shift, single; } emap;
static inline emap emake(int M1,int M2){
  emap e; e.single=(M2==1); e.st=ESTRIDE(M1);
  e.m2mask=M2-1; e.m1mask=M1-1;
  e.m2shift=0; while((1<<e.m2shift)<M2) e.m2shift++;
  e.m1shift=0; while((1<<e.m1shift)<M1) e.m1shift++;
  return e;
}
static inline int eidx(const emap *e,int k){        /* slot holding output element k */
  return e->single ? k : e->st*(k & e->m2mask) + (k >> e->m2shift);
}
static inline int einp(const emap *e,int n){        /* slot to place input element n */
  return e->single ? n : (n & e->m1mask) + e->st*(n >> e->m1shift);
}
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
  int a1,a2,b1,b2;      /* codelet factorisation of N1 and N2 */
  emap ea,eb;           /* index maps for those factorisations */
} BP;

/* ---- element-space transform of size M, lanes independent ----------------
   Sizes up to 64 are a single generated codelet.  Larger M is a two-level
   four-step over codelet-sized factors M = M1*M2, with the element stride padded
   to M1+1 so the stride-M1 pass does not collapse onto a couple of L1 sets - the
   same padding that was worth 13x on the specialised path.
   Output element k then lives at EIDX(), not at k: the four-step leaves it
   transposed, and undoing that would cost more than indexing around it.        */
static inline int codelet(int m,vf*ar,vf*ai,vf*br,vf*bi,long S){
  switch(m){
    case  8: return fft8_42 (ar,ai,br,bi,S);
    case 16: return fft16_44(ar,ai,br,bi,S);
    case 32: return fft32_84(ar,ai,br,bi,S);
    default: return fft64_88(ar,ai,br,bi,S);
  }
}
static void efft(int M,vf*X,vf*Xi,vf*S,vf*Si,const float*wr,const float*wi){
  int M1,M2; efactor(M,&M1,&M2);
  if(M2==1){ codelet(M,X,Xi,S,Si,1); return; }
  const int st=ESTRIDE(M1);
  for(int e1=0;e1<M1;e1++) codelet(M2,X+e1,Xi+e1,S+e1,Si+e1,st);
  for(int k2p=0;k2p<M2;k2p++) for(int e1=0;e1<M1;e1++){
    int idx=e1+st*k2p, t=(e1*k2p)&(M-1);
    vf cr=V_SET1(wr[t]),ci=V_SET1(wi[t]);
    vf xr=X[idx],xi=Xi[idx];
    X[idx] =V_FMSUB(xr,cr,V_MUL(xi,ci));
    Xi[idx]=V_FMADD(xr,ci,V_MUL(xi,cr));
  }
  for(int k2p=0;k2p<M2;k2p++)
    codelet(M1,X+st*k2p,Xi+st*k2p,S+st*k2p,Si+st*k2p,1);
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
  efactor(n1,&p->a1,&p->a2); efactor(n2,&p->b1,&p->b2);
  p->ea=emake(p->a1,p->a2); p->eb=emake(p->b1,p->b2);
  int a1,a2,b1,b2; efactor(n1,&a1,&a2); efactor(n2,&b1,&b2);
  size_t s1=(a2==1)?(size_t)n1:(size_t)ESTRIDE(a1)*a2;
  size_t s2=(b2==1)?(size_t)n2:(size_t)ESTRIDE(b1)*b2;
  size_t me=s1>s2?s1:s2;
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
      int q=einp(&p->eb,n2);
      p->bR[q]=r; p->bI[q]=V_XOR(i,sg);
    }
    efft(N2,p->bR,p->bI,p->sR,p->sI,p->w2r,p->w2i);
    vf *RR=p->bR,*RI=p->bI;
    for(int b=0;b<N2/PF_W;b++){
      for(int t=0;t<PF_W;t++){
        int k2=PF_W*b+t;
        unsigned mm=((unsigned)g*(unsigned)k2)&p->nmask, m1=mm>>8, m0=mm&255;
        float sr=p->hr[m1]*p->lr[m0]-p->hi[m1]*p->li[m0];
        float si=p->hr[m1]*p->li[m0]+p->hi[m1]*p->lr[m0];
        vf SR=V_SET1(sr),SI=V_SET1(si);
        vf tr=V_FMSUB(SR,p->TLr[k2],V_MUL(SI,p->TLi[k2]));
        vf ti=V_FMADD(SR,p->TLi[k2],V_MUL(SI,p->TLr[k2]));
        int eb=eidx(&p->eb,k2);
        vf xr=RR[eb],xi=RI[eb];
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
    int q=einp(&p->ea,n1);
    p->bR[q]=V_LOADU(p->ire+off); p->bI[q]=V_LOADU(p->iim+off);
  }
  efft(N1,p->bR,p->bI,p->sR,p->sI,p->w1r,p->w1i);
  *RR=p->bR; *RI=p->bI;
}

void FN(fft)(void *vp,const float*in,float*out,int conj){
  BP *p=vp; const int N1=p->N1,N2=p->N2;
  const vf sg = conj?V_SIGNMASK():V_ZERO();
  stageA(p,in,conj);
  for(int b=0;b<N2/PF_W;b++){
    vf *RR,*RI; stageB(p,b,&RR,&RI);
    for(int k1=0;k1<N1;k1++){ int e=eidx(&p->ea,k1);
      v_inter(out+2*((size_t)k1*N2+PF_W*b),RR[e],V_XOR(RI[e],sg)); }
  }
}

int FN(topk)(void *vp,const float*in,int K,pf_peak*out,int conj,size_t ws,size_t we){
  BP *p=vp; const int N1=p->N1,N2=p->N2;
  stageA(p,in,conj);
  cand T[PF_MAX_K]; int n=0; float thr=-1.f;
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
    vf *RR,*RI; stageB(p,b,&RR,&RI);
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
          push(T,K,&n,bm[l],k0+l,br[l],bi[l]);
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
