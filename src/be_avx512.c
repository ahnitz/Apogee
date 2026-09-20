/* peakfft: the specialised AVX-512 back end.
   N=1024 uses the L1-resident four-step kernel; 2^12..2^16 the balanced split;
   2^17..2^20 the traffic-minimising path with a 24-bit quantised intermediate. */
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <immintrin.h>
#include "peakfft.h"
#include "internal.h"
#include "backend.h"

typedef struct {
  size_t N;
  float *re, *im;                 /* SoA scratch (N=1024 path) */
  __m512 t4r[2][32], t4i[2][32];  /* 32x32 corner-turn twiddles */
  void *bal;          /* codelet-based balanced split (src/balanced.c) */
} AP;

void pf_push(pf_cand *T,int K,int *n,float m2,int idx,float vr,float vi){
  if(*n<K){ int i=(*n)++; T[i].mag2=m2; T[i].idx=idx; T[i].re=vr; T[i].im=vi;
    while(i>0&&T[i].mag2<T[(i-1)/2].mag2){ pf_cand t=T[i];T[i]=T[(i-1)/2];T[(i-1)/2]=t; i=(i-1)/2; } return; }
  if(m2<=T[0].mag2) return;
  T[0].mag2=m2; T[0].idx=idx; T[0].re=vr; T[0].im=vi; int i=0;
  for(;;){ int l=2*i+1,r=l+1,s=i;
    if(l<K&&T[l].mag2<T[s].mag2) s=l;
    if(r<K&&T[r].mag2<T[s].mag2) s=r;
    if(s==i) break;
    { pf_cand t=T[i];T[i]=T[s];T[s]=t; } i=s; }
}

/* Same idea as the full-range prime, but restricted to whole 16-lane blocks that
   lie strictly inside [lo,hi).  Every candidate is then a real in-window element,
   so the K-th largest of the per-lane maxima is still a safe lower bound - and the
   windowed scan keeps the tight threshold instead of falling back to a push storm. */
static float prime_range(const float *re,const float *im,long lo,long hi,int K){
  long a=(lo+15)&~15L, b=hi&~15L;
  if(K>16 || b<=a) return -1.f;
  __m512 vmax=_mm512_setzero_ps();
  for(long k=a;k<b;k+=16){
    __m512 r=_mm512_load_ps(re+k), i=_mm512_load_ps(im+k);
    vmax=_mm512_max_ps(vmax,_mm512_fmadd_ps(r,r,_mm512_mul_ps(i,i)));
  }
  float lm[16]; _mm512_storeu_ps(lm,vmax);
  int kk=K<16?K:16;
  for(int x=0;x<kk;x++){ int y=x;
    for(int c=x+1;c<16;c++) if(lm[c]>lm[y]) y=c;
    float t=lm[x]; lm[x]=lm[y]; lm[y]=t; }
  return nextafterf(lm[kk-1],-1.f);
}

float pf_prime_threshold(const float *re,const float *im,int n,int K){
  /* One branch-free pass gives 16 per-lane maxima.  Those are 16 genuine array
     elements, so their K-th largest never exceeds the K-th largest overall and is a
     safe scan threshold - and it is far tighter than a blanket -1, which is what
     makes the following pass almost never branch.  K>16 falls back to no priming. */
  if(K>16) return -1.f;
  __m512 vmax=_mm512_setzero_ps();
  for(int k=0;k<n;k+=16){
    __m512 r=_mm512_load_ps(re+k), i=_mm512_load_ps(im+k);
    vmax=_mm512_max_ps(vmax,_mm512_fmadd_ps(r,r,_mm512_mul_ps(i,i)));
  }
  float lm[16]; _mm512_storeu_ps(lm,vmax);
  for(int a=0;a<K;a++){ int b=a;
    for(int c=a+1;c<16;c++) if(lm[c]>lm[b]) b=c;
    float t=lm[a]; lm[a]=lm[b]; lm[b]=t; }
  return nextafterf(lm[K-1],-1.f);
}

static int a512_supported(size_t N){
  if(N==1024u) return 1;
  return N>=4096u && N<=1048576u && (N&(N-1))==0u;   /* 2^12 .. 2^20 */
}

static void *a512_create(size_t N){
  if(!a512_supported(N)) return NULL;
  AP *p = aligned_alloc(64, sizeof(*p));
  if(!p) return NULL;
  memset(p,0,sizeof(*p));
  p->N=N;
  for(int c=0;c<2;c++) for(int k2=0;k2<32;k2++){
    float tr[16],ti[16];
    for(int l=0;l<16;l++){ int n1=16*c+l; double a=-2.0*M_PI*(double)n1*k2/1024.0;
      tr[l]=(float)cos(a); ti[l]=(float)sin(a); }
    p->t4r[c][k2]=_mm512_loadu_ps(tr); p->t4i[c][k2]=_mm512_loadu_ps(ti);
  }
  if(N==1024){
    p->re=aligned_alloc(64,1024*sizeof(float));
    p->im=aligned_alloc(64,1024*sizeof(float));
  } else {
    p->bal = pf_be_bal16.create(N);
    if(!p->bal){ free(p); return NULL; }
  }
  return p;
}

static void a512_destroy(void *vp){
  AP *p=vp; if(!p) return;
  free(p->re); free(p->im);
  if(p->bal) pf_be_bal16.destroy(p->bal);
  free(p);
}

static void a512_fft(void *vp,const float *in,float *out,int conj){
  AP *p=vp;
  if(p->N==1024){
    pf_deint_c(in,p->re,p->im,1024,conj);
    pf_fft1024_soa(p->re,p->im,p->t4r,p->t4i);
    pf_inter_c(p->re,p->im,out,1024,conj);
  } else {
    pf_be_bal16.fft(p->bal,in,out,conj);
  }
}

static int a512_topk(void *vp,const float *in,int K,pf_peak *peaks,int conj,size_t ws,size_t we,float thr0){
  AP *p=vp;
  if(K<1) return 0;
  if(K>PF_MAX_K) K=PF_MAX_K;
  if(p->N==1024 && thr0>0.f){
    /* With a floor supplied up front the search fuses into the transform: no scan
       pass, and only blocks that produce a candidate are ever stored. */
    pf_cand T[PF_MAX_K];
    pf_deint_c(in,p->re,p->im,1024,conj);
    int n=pf_fft1024_topk(p->re,p->im,p->t4r,p->t4i,thr0*thr0,(long)ws,(long)we,K,T);
    for(int a=1;a<n;a++){ pf_cand v=T[a]; int b=a-1;
      while(b>=0&&T[b].mag2<v.mag2){T[b+1]=T[b];b--;} T[b+1]=v; }
    for(int a=0;a<n;a++){ peaks[a].index=T[a].idx; peaks[a].re=T[a].re;
      peaks[a].im=conj?-T[a].im:T[a].im; peaks[a].magnitude=sqrtf(T[a].mag2); }
    return n;
  }
  if(p->N==1024){
    /* |X|^2 and the per-lane maxima come out of the transform's final stage, where
       the values are already in registers - so the scan needs no pass of its own and
       starts from a threshold tight enough that it almost never branches. */
    __m512 vmax;
    pf_deint_c(in,p->re,p->im,1024,conj);
    pf_fft1024_soa_mag(p->re,p->im,p->t4r,p->t4i,&vmax);
    float lm[16]; _mm512_storeu_ps(lm,vmax);
    int full = (ws==0 && we>=1024);
    int kk = K<16?K:16;
    for(int a=0;a<kk;a++){ int b=a;
      for(int c=a+1;c<16;c++) if(lm[c]>lm[b]) b=c;
      float t=lm[a]; lm[a]=lm[b]; lm[b]=t; }
    float thr = full ? ((K<=16) ? nextafterf(lm[kk-1],-1.f) : -1.f)
                     : prime_range(p->re,p->im,(long)ws,(long)we,K);
    /* a supplied detection floor can only tighten the primed threshold */
    if(thr0>0.f && thr0*thr0>thr) thr=thr0*thr0;
    pf_cand T[PF_MAX_K]; int n=0;
    __m512 vthr=_mm512_set1_ps(thr);
    long lo=(long)ws & ~15L, hi=(long)we;
    for(long k=lo;k<hi;k+=16){
      __mmask16 inw=0xFFFF;
      if(k<(long)ws || k+16>(long)we){
        inw=0;
        for(int l=0;l<16;l++){ long kk2=k+l;
          if(kk2>=(long)ws && kk2<(long)we) inw|=(__mmask16)(1u<<l); }
        if(!inw) continue;
      }
      __m512 r=_mm512_load_ps(p->re+k), i2=_mm512_load_ps(p->im+k);
      __m512 m2=_mm512_fmadd_ps(r,r,_mm512_mul_ps(i2,i2));
      __mmask16 msk=_mm512_cmp_ps_mask(m2,vthr,_CMP_GT_OQ)&inw;
      if(msk){
        float bb[16]; _mm512_storeu_ps(bb,m2);
        while(msk){
          int l=__builtin_ctz((unsigned)msk); msk&=(__mmask16)(msk-1);
          if(bb[l]<=thr) continue;
          pf_push(T,K,&n,bb[l],(int)(k+l),p->re[k+l],p->im[k+l]);
          if(n==K){ thr=T[0].mag2; vthr=_mm512_set1_ps(thr); }
        }
      }
    }
    for(int a=1;a<n;a++){ pf_cand v=T[a]; int b=a-1; while(b>=0&&T[b].mag2<v.mag2){T[b+1]=T[b];b--;} T[b+1]=v; }
    for(int a=0;a<n;a++){ peaks[a].index=T[a].idx; peaks[a].re=T[a].re;
      peaks[a].im=conj?-T[a].im:T[a].im; peaks[a].magnitude=sqrtf(T[a].mag2); }
    return n;
  }
  return pf_be_bal16.topk(p->bal,in,K,peaks,conj,ws,we,thr0);
}

static int a512_topk_q(void *vp,const short*qhi,const signed char*qlo,const float*qs,
                       int K,pf_peak*out,int conj,size_t ws,size_t we,float thr0){
  AP *p=vp;
  if(!p->bal) return -1;               /* N=1024 uses the specialised kernel */
  return pf_be_bal16.topk_q(p->bal,qhi,qlo,qs,K,out,conj,ws,we,thr0);
}
static void a512_quantize(void *vp,const float*in,short*qhi,signed char*qlo,float*qs){
  AP *p=vp;
  if(p->bal) pf_be_bal16.quantize(p->bal,in,qhi,qlo,qs);
}
const pf_backend pf_be_avx512 = {
  "avx512", a512_create, a512_destroy, a512_fft, a512_topk, a512_supported,
  a512_topk_q, a512_quantize
};
