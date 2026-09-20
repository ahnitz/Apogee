/* peakfft: batched matched filter.
 *
 * D data segments x T templates, reporting the binned maximum of each pair's
 * correlation.  See docs/matched-filter-plan.md for where the time goes and which
 * reuse opportunities are real.
 *
 * Round 0 is deliberately the obvious implementation: form the product, hand it
 * to the existing backward binned-max path.  It exists so the test suite is
 * meaningful before any of the interesting optimisations go in, and so each of
 * those can be A/B'd against something known-correct.
 */
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <immintrin.h>
#include "peakfft.h"

/* Split-layout spectrum product.  Templates are stored already conjugated, so
 * this is a plain complex multiply, conjugated on output because the backward
 * transform wants conj(product) - which costs nothing, being the same two FMAs
 * with the signs swapped.  Both sides split means no permutes at all.  The interleaved version this
 * replaced needed four permutes per 16 complex on top of the arithmetic. */
__attribute__((target("avx512f")))
static void mulspec_avx512(const float *ar,const float *ai,
                           const float *br,const float *bi,
                           float *or_,float *oi,size_t n){
  for(size_t k=0;k<n;k+=16){
    __m512 x=_mm512_loadu_ps(ar+k), y=_mm512_loadu_ps(ai+k);
    __m512 u=_mm512_loadu_ps(br+k), v=_mm512_loadu_ps(bi+k);
    _mm512_storeu_ps(or_+k,_mm512_fmsub_ps(x,u,_mm512_mul_ps(y,v)));
    /* negated: the backward transform wants conj(product), and conj(D*T) costs
       nothing here - it is the same two FMAs with the signs swapped */
    _mm512_storeu_ps(oi+k, _mm512_fnmsub_ps(x,v,_mm512_mul_ps(y,u)));
  }
}
__attribute__((target("avx2,fma")))
static void mulspec_avx2(const float *ar,const float *ai,
                         const float *br,const float *bi,
                         float *or_,float *oi,size_t n){
  for(size_t k=0;k<n;k+=8){
    __m256 x=_mm256_loadu_ps(ar+k), y=_mm256_loadu_ps(ai+k);
    __m256 u=_mm256_loadu_ps(br+k), v=_mm256_loadu_ps(bi+k);
    _mm256_storeu_ps(or_+k,_mm256_fmsub_ps(x,u,_mm256_mul_ps(y,v)));
    _mm256_storeu_ps(oi+k, _mm256_fnmsub_ps(x,v,_mm256_mul_ps(y,u)));
  }
}
static void mulspec(const float *ar,const float *ai,const float *br,const float *bi,
                    float *or_,float *oi,size_t n){
  if(__builtin_cpu_supports("avx512f") && !(n&15)){ mulspec_avx512(ar,ai,br,bi,or_,oi,n); return; }
  if(__builtin_cpu_supports("avx2")   && !(n&7)) { mulspec_avx2  (ar,ai,br,bi,or_,oi,n); return; }
  for(size_t k=0;k<n;k++){
    float x=ar[k],y=ai[k],u=br[k],v=bi[k];
    or_[k]=x*u-y*v; oi[k]=-(x*v+y*u);
  }
}

struct pf_mf_plan {
  size_t n;
  int nd, nt;
  pf_plan *fft;        /* shared transform plan: forward at ingest, backward per pair */
  /* Spectra are stored SPLIT (re and im in separate arrays), which is what the
     transform wants.  Preprocessing is free here - every segment is ingested once
     and used D or T times - so it is done in the layout the hot loop prefers, and
     the product becomes four FMAs with no permutes and no deinterleave. */
  float *dre,*dim;     /* [nd][n] */
  float *tre,*tim;     /* [nt][n], already conjugated */
  float *pr,*pi;       /* scratch for one product, split */
  float *scratch;      /* interleaved staging for ingest */
};

pf_mf_plan *pf_mf_create(size_t n, int ndata, int ntmpl){
  if(ndata<1||ntmpl<1) return NULL;
  pf_mf_plan *p = calloc(1,sizeof(*p));
  if(!p) return NULL;
  p->n=n; p->nd=ndata; p->nt=ntmpl;
  p->fft = pf_create(n);
  if(!p->fft){ free(p); return NULL; }
  p->dre=aligned_alloc(64,(size_t)ndata*n*sizeof(float));
  p->dim=aligned_alloc(64,(size_t)ndata*n*sizeof(float));
  p->tre=aligned_alloc(64,(size_t)ntmpl*n*sizeof(float));
  p->tim=aligned_alloc(64,(size_t)ntmpl*n*sizeof(float));
  p->pr =aligned_alloc(64,n*sizeof(float));
  p->pi =aligned_alloc(64,n*sizeof(float));
  p->scratch=aligned_alloc(64,2*n*sizeof(float));
  if(!p->dre||!p->dim||!p->tre||!p->tim||!p->pr||!p->pi||!p->scratch){
    pf_mf_destroy(p); return NULL; }
  return p;
}

void pf_mf_destroy(pf_mf_plan *p){
  if(!p) return;
  if(p->fft) pf_destroy(p->fft);
  free(p->dre);free(p->dim);free(p->tre);free(p->tim);
  free(p->pr);free(p->pi);free(p->scratch);
  free(p);
}

size_t pf_mf_nbins(const pf_mf_plan *p, size_t binsize, size_t start, size_t end){
  if(!p||!binsize) return 0;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  return (end-start+binsize-1)/binsize;
}

static void split_store(const float *inter,float *re,float *im,size_t n,int conj){
  for(size_t k=0;k<n;k++){ re[k]=inter[2*k]; im[k]=conj?-inter[2*k+1]:inter[2*k+1]; }
}

int pf_mf_set_data(pf_mf_plan *p, int d, const float *seg){
  if(!p||d<0||d>=p->nd) return -1;
  pf_fft(p->fft, seg, p->scratch, PF_FORWARD);
  split_store(p->scratch, p->dre+(size_t)d*p->n, p->dim+(size_t)d*p->n, p->n, 0);
  return 0;
}

int pf_mf_set_template(pf_mf_plan *p, int t, const float *tmpl){
  if(!p||t<0||t>=p->nt) return -1;
  pf_fft(p->fft, tmpl, p->scratch, PF_FORWARD);
  /* conjugate at ingest, not per pair: this runs T times, the pair loop D*T */
  split_store(p->scratch, p->tre+(size_t)t*p->n, p->tim+(size_t)t*p->n, p->n, 1);
  return 0;
}

int pf_mf_run(pf_mf_plan *p, int d0, int nd, int t0, int nt,
              size_t binsize, float threshold,
              pf_peak *peaks, int *counts, size_t start, size_t end){
  if(!p||nd<1||nt<1||!binsize) return 0;
  if(d0<0||d0+nd>p->nd||t0<0||t0+nt>p->nt) return -1;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  const size_t n=p->n, nb=(end-start+binsize-1)/binsize;
  int total=0;
  for(int d=0;d<nd;d++){
    const float *Dr=p->dre+(size_t)(d0+d)*n, *Di=p->dim+(size_t)(d0+d)*n;
    for(int t=0;t<nt;t++){
      const float *Hr=p->tre+(size_t)(t0+t)*n, *Hi=p->tim+(size_t)(t0+t)*n;
      mulspec(Dr,Di,Hr,Hi,p->pr,p->pi,n);
      size_t row=(size_t)d*nt+t;
      int c=0;
      int r = pf_binmax_split(p->fft,p->pr,p->pi,binsize,threshold,
                              peaks+row*nb,&c,PF_BACKWARD,start,end);
      if(r<0) return -1;
      if(counts) counts[row]=c;
      total += c;
    }
  }
  return total;
}
