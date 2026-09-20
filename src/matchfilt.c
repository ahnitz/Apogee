/* apogee: batched matched filter.
 *
 * D data segments x T templates, reporting the binned maximum of each pair's
 * correlation.  See docs/matched-filter-plan.md for where the time goes and which
 * reuse opportunities are real.
 *
 * Segments arrive already transformed.  Ingest only rearranges - conjugate the
 * templates, and store both sides group-major so every pair transform reads
 * sequentially - which keeps the D*T loop free of anything single-sided.
 */
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <immintrin.h>
#include "apogee.h"

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

struct ap_mf_plan {
  size_t n;
  int nd, nt;
  ap_plan *fft;        /* shared transform plan: forward at ingest, backward per pair */
  int n1,n2,w;         /* the transform's split and lane count, for group-major storage */
  int gmajor;          /* 0 when the back end cannot take group-major input     */
  /* Spectra are stored SPLIT (re and im in separate arrays), which is what the
     transform wants.  Preprocessing is free here - every segment is ingested once
     and used D or T times - so it is done in the layout the hot loop prefers, and
     the product becomes four FMAs with no permutes and no deinterleave. */
  float *dre,*dim;     /* [nd][n] */
  float *tre,*tim;     /* [nt][n], already conjugated */
  float *pr,*pi;       /* scratch for one product, split */
  float *scratch;      /* interleaved staging for ingest */
};

ap_mf_plan *ap_mf_create(size_t n, int ndata, int ntmpl){
  if(ndata<1||ntmpl<1) return NULL;
  ap_mf_plan *p = calloc(1,sizeof(*p));
  if(!p) return NULL;
  p->n=n; p->nd=ndata; p->nt=ntmpl;
  p->fft = ap_create(n);
  if(!p->fft){ free(p); return NULL; }
  /* mirror the back end's split so ingest can lay spectra out the way stage A
     walks them; if anything does not line up, fall back to plain split storage */
  { int m=0; while(((size_t)1<<m)<n) m++;
    p->n1=1<<((m+1)/2); p->n2=1<<(m/2);
    p->w = ap_lane_width();
    p->gmajor = (p->w>0 && p->n1%p->w==0 && n!=1024) ? 1 : 0;
    const char *e=getenv("APOGEE_GMAJOR"); if(e && !atoi(e)) p->gmajor=0;
  }
  p->dre=aligned_alloc(64,(size_t)ndata*n*sizeof(float));
  p->dim=aligned_alloc(64,(size_t)ndata*n*sizeof(float));
  p->tre=aligned_alloc(64,(size_t)ntmpl*n*sizeof(float));
  p->tim=aligned_alloc(64,(size_t)ntmpl*n*sizeof(float));
  p->pr =aligned_alloc(64,n*sizeof(float));
  p->pi =aligned_alloc(64,n*sizeof(float));
  p->scratch=aligned_alloc(64,2*n*sizeof(float));
  if(!p->dre||!p->dim||!p->tre||!p->tim||!p->pr||!p->pi||!p->scratch){
    ap_mf_destroy(p); return NULL; }
  return p;
}

void ap_mf_destroy(ap_mf_plan *p){
  if(!p) return;
  if(p->fft) ap_destroy(p->fft);
  free(p->dre);free(p->dim);free(p->tre);free(p->tim);
  free(p->pr);free(p->pi);free(p->scratch);
  free(p);
}

size_t ap_mf_nbins(const ap_mf_plan *p, size_t binsize, size_t start, size_t end){
  if(!p||!binsize) return 0;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  return (end-start+binsize-1)/binsize;
}

/* Store a spectrum split AND group-major: [n1 block][n2][lane], n1 = g*W + l,
   from the natural x[n2*N1 + n1].  This is a transpose, paid once per segment at
   ingest, so that every one of the D*T pair transforms reads sequentially.  It is
   the whole reason preprocessing being free matters. */
static void split_store(const float *inter,float *re,float *im,size_t n,int conj,
                        int n1,int n2,int w){
  if(n1<=0||n2<=0||w<=0||(size_t)n1*n2!=n){
    for(size_t k=0;k<n;k++){ re[k]=inter[2*k]; im[k]=conj?-inter[2*k+1]:inter[2*k+1]; }
    return;
  }
  const int ng=n1/w;
  for(int g=0;g<ng;g++)
    for(int b=0;b<n2;b++)
      for(int l=0;l<w;l++){
        size_t src=(size_t)b*n1+(size_t)g*w+l;      /* x[n2*N1 + n1] */
        size_t dst=(size_t)g*n2*w+(size_t)b*w+l;
        re[dst]=inter[2*src];
        im[dst]=conj?-inter[2*src+1]:inter[2*src+1];
      }
}

int ap_mf_set_data(ap_mf_plan *p, int d, const float *spec){
  if(!p||d<0||d>=p->nd) return -1;
  split_store(spec, p->dre+(size_t)d*p->n, p->dim+(size_t)d*p->n, p->n, 0,
              p->gmajor?p->n1:0, p->n2, p->w);
  return 0;
}

int ap_mf_set_template(ap_mf_plan *p, int t, const float *spec){
  if(!p||t<0||t>=p->nt) return -1;
  /* conjugate at ingest, not per pair: this runs T times, the pair loop D*T */
  split_store(spec, p->tre+(size_t)t*p->n, p->tim+(size_t)t*p->n, p->n, 1,
              p->gmajor?p->n1:0, p->n2, p->w);
  return 0;
}

int ap_mf_run(ap_mf_plan *p, int d0, int nd, int t0, int nt,
              size_t binsize, float threshold,
              ap_peak *peaks, int *counts, size_t start, size_t end){
  if(!p||nd<1||nt<1||!binsize) return 0;
  if(d0<0||d0+nd>p->nd||t0<0||t0+nt>p->nt) return -1;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  const size_t n=p->n, nb=(end-start+binsize-1)/binsize;
  /* Tile the pair loop.  Running d outer already keeps one data spectrum resident
     across the t loop, but every template then streams once per d: D*(1+T)
     spectrum reads.  A tile of nd x nt reads nd+nt spectra and does nd*nt pairs,
     so the count falls to (D/nd)(T/nt)(nd+nt).  Tile size is bounded by how many
     spectra fit - each is 2n floats - and there is no point tiling at all once
     two of them fill the cache. */
  size_t spec=2*n*sizeof(float);
  /* Measured at 16x16: 2^12 3.40 -> 2.98 (tile 8), 2^14 12.96 -> 12.34, 2^16
     within noise once two spectra fill L2.  8 is never worse, so take it. */
  (void)spec;
  int tile = 8;
  { const char *e=getenv("APOGEE_MFTILE"); if(e){ int v=atoi(e); if(v>0) tile=v; } }
  int total=0;
  for(int dt=0;dt<nd;dt+=tile) for(int tt=0;tt<nt;tt+=tile){
   const int dend=(nd-dt<tile)?nd:dt+tile, tend=(nt-tt<tile)?nt:tt+tile;
   for(int d=dt;d<dend;d++){
    const float *Dr=p->dre+(size_t)(d0+d)*n, *Di=p->dim+(size_t)(d0+d)*n;
    for(int t=tt;t<tend;t++){
      const float *Hr=p->tre+(size_t)(t0+t)*n, *Hi=p->tim+(size_t)(t0+t)*n;
      size_t row=(size_t)d*nt+t;
      int c=0;
      /* fused path where the back end has one; otherwise form the product and
         hand it over, which is what N=1024 does - 8 KiB in L1 is not worth a
         second specialised kernel */
      int r = p->gmajor ? ap_binmax_prod(p->fft,Dr,Di,Hr,Hi,binsize,threshold,
                                         peaks+row*nb,&c,AP_BACKWARD,start,end)
                        : -1;
      if(r<0){
        mulspec(Dr,Di,Hr,Hi,p->pr,p->pi,n);
        r = ap_binmax_split(p->fft,p->pr,p->pi,binsize,threshold,
                            peaks+row*nb,&c,AP_BACKWARD,start,end);
      }
      if(r<0) return -1;
      if(counts) counts[row]=c;
      total += c;
    }
   }
  }
  return total;
}
