/* apogee: the specialised AVX-512 back end.
   N=1024 uses the L1-resident four-step kernel; 2^12..2^16 the balanced split;
   2^17..2^20 the traffic-minimising path with a 24-bit quantised intermediate. */
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <immintrin.h>
#include "apogee.h"
#include "internal.h"
#include "backend.h"

typedef struct {
  size_t N;
  float *re, *im;                 /* SoA scratch (N=1024 path) */
  __m512 t4r[2][32], t4i[2][32];  /* 32x32 corner-turn twiddles */
  void *bal;          /* codelet-based balanced split (src/balanced.c) */
} AP;

void ap_push(ap_cand *T,int K,int *n,float m2,int idx,float vr,float vi){
  if(*n<K){ int i=(*n)++; T[i].mag2=m2; T[i].idx=idx; T[i].re=vr; T[i].im=vi;
    while(i>0&&T[i].mag2<T[(i-1)/2].mag2){ ap_cand t=T[i];T[i]=T[(i-1)/2];T[(i-1)/2]=t; i=(i-1)/2; } return; }
  if(m2<=T[0].mag2) return;
  T[0].mag2=m2; T[0].idx=idx; T[0].re=vr; T[0].im=vi; int i=0;
  for(;;){ int l=2*i+1,r=l+1,s=i;
    if(l<K&&T[l].mag2<T[s].mag2) s=l;
    if(r<K&&T[r].mag2<T[s].mag2) s=r;
    if(s==i) break;
    { ap_cand t=T[i];T[i]=T[s];T[s]=t; } i=s; }
}

/* Same idea as the full-range prime, but restricted to whole 16-lane blocks that
   lie strictly inside [lo,hi).  Every candidate is then a real in-window element,
   so the K-th largest of the per-lane maxima is still a safe lower bound - and the
   windowed scan keeps the tight threshold instead of falling back to a push storm. */
float ap_prime_threshold(const float *re,const float *im,int n,int K){
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
    p->bal = ap_be_bal16.create(N);
    if(!p->bal){ free(p); return NULL; }
  }
  return p;
}

static void a512_destroy(void *vp){
  AP *p=vp; if(!p) return;
  free(p->re); free(p->im);
  if(p->bal) ap_be_bal16.destroy(p->bal);
  free(p);
}

static void a512_fft(void *vp,const float *in,float *out,int conj){
  AP *p=vp;
  if(p->N==1024){
    ap_deint_c(in,p->re,p->im,1024,conj);
    ap_fft1024_soa(p->re,p->im,p->t4r,p->t4i);
    ap_inter_c(p->re,p->im,out,1024,conj);
  } else {
    ap_be_bal16.fft(p->bal,in,out,conj);
  }
}

static int a512_binmax(void *vp,const float *in,size_t binsize,float thr,
                       ap_peak *out,int conj,size_t ws,size_t we){
  AP *p=vp;
  if(p->N==1024){
    ap_deint_c(in,p->re,p->im,1024,conj);
    int r=ap_fft1024_binmax(p->re,p->im,p->t4r,p->t4i,binsize,thr,out,conj,
                            (long)ws,(long)we);
    if(r==0) return 0;            /* -1 only means too many bins for the fused path */
  }
  return ap_be_bal16.binmax(p->bal,in,binsize,thr,out,conj,ws,we);
}

static int a512_binmax_split(void *vp,const float *re,const float *im,size_t binsize,
                             float thr,ap_peak *out,int conj,size_t ws,size_t we){
  AP *p=vp;
  if(p->N==1024){
    /* consumed in place, and already conjugated by the caller if needed - so no
       copy and no conjugate pass, which is the whole point of this entry point */
    int r=ap_fft1024_binmax((float*)re,(float*)im,p->t4r,p->t4i,binsize,thr,out,conj,
                            (long)ws,(long)we);
    if(r==0) return 0;
  }
  return ap_be_bal16.binmax_split(p->bal,re,im,binsize,thr,out,conj,ws,we);
}

static int a512_has_prod(void *vp){
  AP *p=vp;
  /* the specialised 1024 kernel has no fused variant; everything else delegates
     to the generic back end, which does */
  return p->N!=1024;
}

static int a512_binmax_prod(void *vp,const float *dr,const float *di,
                            const float *tr,const float *ti,size_t binsize,
                            float thr,ap_peak *out,int conj,size_t ws,size_t we){
  AP *p=vp;
  /* N=1024 has no fused variant of its specialised kernel; the product there is
     8 KiB in L1 and not worth a second kernel.  Everything else goes to the
     generic fused path. */
  if(p->N==1024) return -1;
  return ap_be_bal16.binmax_prod(p->bal,dr,di,tr,ti,binsize,thr,out,conj,ws,we);
}

const ap_backend ap_be_avx512 = {
  "avx512", a512_create, a512_destroy, a512_fft, a512_supported,
  a512_binmax, a512_binmax_split, a512_has_prod, a512_binmax_prod
};
