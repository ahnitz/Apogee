/* matchedfilter: batched matched filter.
 *
 * D data segments x T templates, reporting the binned maximum of each pair's
 * correlation.  See docs/design.md for where the time goes and which
 * reuse opportunities are real.
 *
 * Segments arrive already transformed.  Ingest only rearranges - conjugate the
 * templates, and store both sides group-major so every pair transform reads
 * sequentially - which keeps the D*T loop free of anything single-sided.
 */
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "alloc.h"
#include "matchedfilter.h"
#include "transform.h"

/* Unfused product, for a back end with no fused stage-A loader.  Every
   Highway build has one, so this runs only when MF_GMAJOR=0 disables the
   fused path for a cross-check.  It had hand-written AVX-512 and AVX2
   variants; the compiler vectorises this loop, and keeping two intrinsic
   kernels alive for a diagnostic path was not worth it. */
static void mulspec(const float *ar,const float *ai,const float *br,const float *bi,
                    float *or_,float *oi,size_t n){
  for(size_t k=0;k<n;k++){
    float x=ar[k],y=ai[k],u=br[k],v=bi[k];
    or_[k]=x*u-y*v; oi[k]=-(x*v+y*u);
  }
}

struct ap_mf_plan {
  size_t n;
  int nd, nt;
  int tile;            /* pair-loop tile; read once, not per run */
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
  /* Ask the plan for its split rather than recomputing it.  Deriving it
     independently means the two disagree the moment the heuristic changes, and
     group-major storage is only correct if they agree - forcing a different
     split through MF_N1 used to produce silently wrong answers. */
  { p->n1=p->n2=0;
    if(!ap_plan_split(p->fft,&p->n1,&p->n2)){ p->n1=p->n2=0; }
    p->w = ap_lane_width();
    /* Group-major storage is only correct if the fused loader consumes it, so
       ask the plan rather than assuming.  The AVX-512 1024 kernel has no fused
       variant, but AVX2 at 1024 runs on the generic back end, which does - and
       hard-coding n!=1024 silently cost the AVX2 path its fused product. */
    p->gmajor = (p->w>0 && p->n1>0 && p->n1%p->w==0
                 && (size_t)p->n1*p->n2==n && ap_has_fused_prod(p->fft)) ? 1 : 0;
    const char *e=getenv("MF_GMAJOR"); if(e && !atoi(e)) p->gmajor=0;
  }
  /* Read once here, not inside ap_mf_run.  The hierarchical filter calls
     ap_mf_run once per pair rather than once per batch, which turned a
     per-batch getenv into a per-pair one. */
  p->tile = 8;
  { const char *e=getenv("MF_MFTILE"); if(e){ int v=atoi(e); if(v>0) p->tile=v; } }
  p->dre=ap_alloc64((size_t)ndata*n*sizeof(float));
  p->dim=ap_alloc64((size_t)ndata*n*sizeof(float));
  p->tre=ap_alloc64((size_t)ntmpl*n*sizeof(float));
  p->tim=ap_alloc64((size_t)ntmpl*n*sizeof(float));
  p->pr =ap_alloc64(n*sizeof(float));
  p->pi =ap_alloc64(n*sizeof(float));
  p->scratch=ap_alloc64(2*n*sizeof(float));
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
  const int tile = p->tile;
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
