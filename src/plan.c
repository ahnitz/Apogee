/* peakfft: plan management and public API. */
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <immintrin.h>
#include "peakfft.h"
#include "internal.h"

struct pf_plan {
  size_t N;
  float *re, *im;                 /* SoA scratch (N=1024 path) */
  __m512 t4r[2][32], t4i[2][32];  /* 32x32 corner-turn twiddles */
  P20 *p20;
  PS  *ps;
};

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

int pf_supported(size_t N){
  if(N==1024u) return 1;
  return N>=4096u && N<=1048576u && (N&(N-1))==0u;   /* 2^12 .. 2^20 */
}

pf_plan *pf_create(size_t N){
  if(!pf_supported(N)) return NULL;
  pf_plan *p = aligned_alloc(64, sizeof(*p));
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
  } else if(N<=(1u<<16)){
    p->ps = pfs_create(N);
    if(!p->ps){ free(p); return NULL; }
  } else {
    p->p20 = pf20_create(N);
    if(!p->p20){ free(p); return NULL; }
  }
  return p;
}

void pf_destroy(pf_plan *p){
  if(!p) return;
  free(p->re); free(p->im); pf20_destroy(p->p20); pfs_destroy(p->ps); free(p);
}

void pf_fft(pf_plan *p,const float *in,float *out){
  if(p->N==1024){
    pf_deint(in,p->re,p->im,1024);
    pf_fft1024_soa(p->re,p->im,p->t4r,p->t4i);
    pf_inter(p->re,p->im,out,1024);
  } else if(p->ps){
    pfs_exact(p->ps,in,out);
  } else {
    pf20_exact(p->p20,in,out);
  }
}

int pf_topk(pf_plan *p,const float *in,int K,int *idx,float *re,float *im){
  if(K<1) return 0;
  if(K>PF_MAX_K) K=PF_MAX_K;
  if(p->N==1024){
    pf_deint(in,p->re,p->im,1024);
    pf_fft1024_soa(p->re,p->im,p->t4r,p->t4i);   /* exact; no output interleave needed */
    /* Threshold is primed tight enough that only ~K blocks of 16 ever trigger. */
    pf_cand T[PF_MAX_K]; int n=0;
    float thr=pf_prime_threshold(p->re,p->im,1024,K);
    __m512 vthr=_mm512_set1_ps(thr);
    for(int k=0;k<1024;k+=16){
      __m512 r=_mm512_load_ps(p->re+k), i2=_mm512_load_ps(p->im+k);
      __m512 m2=_mm512_fmadd_ps(r,r,_mm512_mul_ps(i2,i2));
      __mmask16 msk=_mm512_cmp_ps_mask(m2,vthr,_CMP_GT_OQ);
      if(msk){
        float b[16]; _mm512_storeu_ps(b,m2);
        while(msk){
          int l=__builtin_ctz((unsigned)msk); msk&=(__mmask16)(msk-1);
          if(b[l]<=thr) continue;
          pf_push(T,K,&n,b[l],k+l,p->re[k+l],p->im[k+l]);
          if(n==K){ thr=T[0].mag2; vthr=_mm512_set1_ps(thr); }
        }
      }
    }
    for(int a=1;a<n;a++){ pf_cand v=T[a]; int b=a-1; while(b>=0&&T[b].mag2<v.mag2){T[b+1]=T[b];b--;} T[b+1]=v; }
    for(int a=0;a<n;a++){ idx[a]=T[a].idx; re[a]=T[a].re; im[a]=T[a].im; }
    return n;
  }
  if(p->ps) return pfs_topk(p->ps,in,K,idx,re,im);
  return pf20_topk(p->p20,in,K,idx,re,im);
}
