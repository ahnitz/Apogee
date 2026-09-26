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
#define AP_MF_MAXCAND 64

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
  /* Interpolated coarse maximum, when a caller asks for it.  See interp_max. */
  /* run_series staging, allocated on first use so a plan that never
     filters a series does not carry 4n floats it will not touch.
     ONE buffer pair serves a whole group: ap_mf_set_data split_stores
     immediately rather than retaining the pointer, which is what lets
     the flat path skip the per-slot spectrum array the hierarchical
     one needs. */
  float *sfwd,*sspec;         /* [2n] each */
  /* Pair-batched small-N path.  Below AP_W^2 the transform has no balanced
     split, so the back end puts AP_W independent PAIRS in a vector instead of
     AP_W frequencies of one transform -- see create_small() in
     balanced-inl.h.  What that costs here is a different template bank
     layout, and it has to be decided before ingest. */
  int pb;                     /* lanes per batch, 0 when not this path */
  int ntpad;                  /* template rows, rounded up to a multiple of pb */
  float *ebr,*ebi;            /* fallback lane-expanded data */
  float *tsr,*tsi;            /* [n][pb] gathered template group, when needed  */
  ap_peak *pkbuf;             /* [pb][nb] dense results, before placement      */
  size_t pkcap;
  /* Optional second layout, created only when an actual call can use it.
     The balanced plan remains available for small sub-ranges and selections. */
  struct ap_mf_plan *pair_alt;
  unsigned char *alt_dready, *alt_tready;
  int allow_pair_alt;
};

static ap_mf_plan *create_mf(size_t n, int ndata, int ntmpl, int pair){
  if(ndata<1||ntmpl<1) return NULL;
  ap_mf_plan *p = calloc(1,sizeof(*p));
  if(!p) return NULL;
  p->n=n; p->nd=ndata; p->nt=ntmpl;
  p->fft = pair ? ap_create_pairbatch(n) : ap_create(n);
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
  p->pb = ap_plan_pairbatch(p->fft);
  const int broadcast_data = ap_plan_broadcast_data(p->fft);
  /* Only the measured x86 targets opt in. MF_PBMAX remains a way to force
     either implementation in one build, without changing process state here. */
  const char *isa=ap_plan_backend(p->fft);
  p->allow_pair_alt = !pair && !p->pb && n>=256 && n<=1024 && ntmpl>=16
    && !getenv("MF_PBMAX")
    && (!strcmp(isa,"AVX3") || !strcmp(isa,"AVX2") || !strcmp(isa,"SSE4"));
  p->ntpad = p->pb ? ((ntmpl + p->pb - 1)/p->pb)*p->pb : ntmpl;
  p->dre=ap_alloc64((size_t)ndata*n*sizeof(float));
  p->dim=ap_alloc64((size_t)ndata*n*sizeof(float));
  p->tre=ap_alloc64((size_t)p->ntpad*n*sizeof(float));
  p->tim=ap_alloc64((size_t)p->ntpad*n*sizeof(float));
  p->pr =ap_alloc64(n*sizeof(float));
  p->pi =ap_alloc64(n*sizeof(float));
  p->scratch=ap_alloc64(2*n*sizeof(float));
  if(!p->dre||!p->dim||!p->tre||!p->tim||!p->pr||!p->pi||!p->scratch){
    ap_mf_destroy(p); return NULL; }
  if(p->pb){
    if(!broadcast_data){
      p->ebr=ap_alloc64((size_t)n*p->pb*sizeof(float));
      p->ebi=ap_alloc64((size_t)n*p->pb*sizeof(float));
      if(!p->ebr||!p->ebi){ ap_mf_destroy(p); return NULL; }
    }
    /* The padding rows are transformed like any other lane and their results
       discarded, so they must be finite -- zero, not whatever malloc left. */
    memset(p->tre,0,(size_t)p->ntpad*n*sizeof(float));
    memset(p->tim,0,(size_t)p->ntpad*n*sizeof(float));
    p->tsr=ap_alloc64((size_t)n*p->pb*sizeof(float));
    p->tsi=ap_alloc64((size_t)n*p->pb*sizeof(float));
    if(!p->tsr||!p->tsi){ ap_mf_destroy(p); return NULL; }
  }
  return p;
}

ap_mf_plan *ap_mf_create(size_t n, int ndata, int ntmpl){
  return create_mf(n,ndata,ntmpl,0);
}

void ap_mf_destroy(ap_mf_plan *p){
  if(!p) return;
  if(p->fft) ap_destroy(p->fft);
  ap_mf_destroy(p->pair_alt);
  free(p->alt_dready); free(p->alt_tready);
  free(p->dre);free(p->dim);free(p->tre);free(p->tim);
  free(p->pr);free(p->pi);free(p->scratch);
  free(p->sfwd);free(p->sspec);
  free(p->ebr);free(p->ebi);free(p->tsr);free(p->tsi);free(p->pkbuf);
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
  if(p->pair_alt){
    ap_mf_set_data(p->pair_alt,d,spec);
    p->alt_dready[d]=1;
  }
  return 0;
}

int ap_mf_set_template(ap_mf_plan *p, int t, const float *spec){
  if(!p||t<0||t>=p->nt) return -1;
  if(p->pb){
    /* Bank stored [group][element][lane], lane = t % pb.  The pair kernel
       reads a whole group as one contiguous [element][lane] run, so the
       transposition is paid once per template here rather than per pair --
       the same trade that makes group-major storage worth it on the
       balanced path. */
    const size_t n=p->n; const int W=p->pb;
    const size_t base=(size_t)(t/W)*n*W + (size_t)(t%W);
    float *re=p->tre+base, *im=p->tim+base;
    for(size_t k=0;k<n;k++){
      re[k*W]= spec[2*k];
      im[k*W]=-spec[2*k+1];          /* conjugated at ingest, as below */
    }
    return 0;
  }
  /* conjugate at ingest, not per pair: this runs T times, the pair loop D*T */
  split_store(spec, p->tre+(size_t)t*p->n, p->tim+(size_t)t*p->n, p->n, 1,
              p->gmajor?p->n1:0, p->n2, p->w);
  if(p->pair_alt){
    ap_mf_set_template(p->pair_alt,t,spec);
    p->alt_tready[t]=1;
  }
  return 0;
}

/* Undo the primary layout once when a row first reaches the alternate plan.
   Subsequent setters populate both layouts directly, outside the pair loop. */
static void restore_spectrum(ap_mf_plan *p,const float *re,const float *im,int conj){
  for(size_t k=0;k<p->n;k++){
    size_t j=k;
    if(p->gmajor){
      size_t a=k%(size_t)p->n1, b=k/(size_t)p->n1;
      j=(a/p->w)*p->n2*p->w+b*p->w+a%p->w;
    }
    p->scratch[2*k]=re[j];
    p->scratch[2*k+1]=conj ? -im[j] : im[j];
  }
}

static ap_mf_plan *pair_alternate(ap_mf_plan *p,int d0,int nd,int t0,int nt){
  if(!p->pair_alt){
    ap_mf_plan *q=create_mf(p->n,p->nd,p->nt,1);
    unsigned char *dr=calloc((size_t)p->nd,1), *tr=calloc((size_t)p->nt,1);
    if(!q || !dr || !tr){ ap_mf_destroy(q); free(dr); free(tr); return NULL; }
    p->pair_alt=q; p->alt_dready=dr; p->alt_tready=tr;
  }
  for(int d=d0;d<d0+nd;d++) if(!p->alt_dready[d]){
    restore_spectrum(p,p->dre+(size_t)d*p->n,p->dim+(size_t)d*p->n,0);
    ap_mf_set_data(p->pair_alt,d,p->scratch); p->alt_dready[d]=1;
  }
  for(int t=t0;t<t0+nt;t++) if(!p->alt_tready[t]){
    restore_spectrum(p,p->tre+(size_t)t*p->n,p->tim+(size_t)t*p->n,1);
    ap_mf_set_template(p->pair_alt,t,p->scratch); p->alt_tready[t]=1;
  }
  return p->pair_alt;
}


/* ---- interpolated coarse maximum -------------------------------------
 *
 * The coarse pass samples the correlation on a stride-R lag grid.  The peak
 * between samples is what the second (odd) transform exists to find, and that
 * costs as much as the first.  Interpolating instead cannot replace it -- the
 * kernel for a critically sampled band needs length -- but it BRACKETS it:
 * a statistic S with measured bounds lo <= S/true <= hi settles every pair
 * whose bracket does not straddle the coarse threshold, and only the rest pay the
 * transform.  See docs/hierarchical.md.
 *
 * Candidates are the largest few even samples.  Measured on captured searches,
 * the rank of the true peak's best even neighbour is 0 at the median and 26 at
 * worst, so a handful suffices; an earlier attempt stopped at 16 and wrongly
 * concluded the route was closed.
 */


/* The pair loop.  `tsel` selects which templates to run: NULL means the
   contiguous range [0,nt), and otherwise tsel[0..nsel) holds local indices into
   that range.  A scattered selection is what the hierarchical filter's second
   stage has - the templates that fired are wherever they fell - and running
   them one call at a time costs 4.65 us/pair against 2.76 us in a batch,
   because every call re-reads the data spectrum for a single template.

   Output rows are indexed by the LOCAL template index either way, so a
   selected run writes into the same layout a full run would, leaving the rows
   it skipped untouched. */
/* The pair loop for the small sizes.
 *
 * Lanes are PAIRS here, so the loop nest inverts: a group of pb templates is
 * one call, and the tiling that exists to keep spectra resident is pointless
 * at lengths where the whole bank fits L1.  The data spectrum is the same in
 * every lane, so it is broadcast into [element][lane] once per segment and
 * reused across every template group -- the one expansion this path pays, and
 * it amortises over pb pairs.
 *
 * Results come back dense [lane][nbins] and are placed by the caller's row
 * index, because a scattered template selection has no single stride. */
static int run_pairs_pb(ap_mf_plan *p, int d0, int nd, int t0, int nt,
                        const int *tsel, int nsel,
                        size_t binsize, float threshold,
                        ap_peak *peaks, int *counts, size_t start, size_t end){
  const size_t n=p->n, nb=(end-start+binsize-1)/binsize;
  const int W=p->pb;
  if(p->pkcap < (size_t)W*nb){
    free(p->pkbuf);
    p->pkbuf=ap_alloc64((size_t)W*nb*sizeof(ap_peak));
    if(!p->pkbuf){ p->pkcap=0; return -1; }
    p->pkcap=(size_t)W*nb;
  }
  int total=0;
  for(int d=0;d<nd;d++){
    const float *Dr=p->dre+(size_t)(d0+d)*n, *Di=p->dim+(size_t)(d0+d)*n;
    if(p->ebr){
      for(size_t k=0;k<n;k++){
        const float a=Dr[k], b=Di[k];
        float *er=p->ebr+k*W, *ei=p->ebi+k*W;
        for(int l=0;l<W;l++){ er[l]=a; ei[l]=b; }
      }
      Dr=p->ebr; Di=p->ebi;
    }
    for(int tt=0;tt<nsel;tt+=W){
      const int cnt=(nsel-tt<W)?nsel-tt:W;
      const int base=t0+tt;
      const float *Tr,*Ti;
      if(!tsel && (base%W)==0){
        /* the group is already contiguous in the bank, padding included */
        Tr=p->tre+(size_t)(base/W)*n*W;
        Ti=p->tim+(size_t)(base/W)*n*W;
      } else {
        memset(p->tsr,0,n*(size_t)W*sizeof(float));
        memset(p->tsi,0,n*(size_t)W*sizeof(float));
        for(int l=0;l<cnt;l++){
          const int t=t0+(tsel?tsel[tt+l]:(tt+l));
          const float *sr=p->tre+(size_t)(t/W)*n*W+(size_t)(t%W);
          const float *si=p->tim+(size_t)(t/W)*n*W+(size_t)(t%W);
          for(size_t k=0;k<n;k++){ p->tsr[k*W+l]=sr[k*W]; p->tsi[k*W+l]=si[k*W]; }
        }
        Tr=p->tsr; Ti=p->tsi;
      }
      if(ap_binmax_prod_batch(p->fft,Dr,Di,Tr,Ti,cnt,binsize,threshold,
                              p->pkbuf,NULL,AP_BACKWARD,start,end)<0) return -1;
      for(int l=0;l<cnt;l++){
        const int t = tsel ? tsel[tt+l] : (tt+l);
        const size_t row=(size_t)d*nt+t;
        int c=0;
        for(size_t j=0;j<nb;j++){
          const ap_peak pk=p->pkbuf[(size_t)l*nb+j];
          peaks[row*nb+j]=pk;
          if(pk.index>=0) c++;
        }
        if(counts) counts[row]=c;
        total+=c;
      }
    }
  }
  return total;
}

static int run_pairs(ap_mf_plan *p, int d0, int nd, int t0, int nt,
                     const int *tsel, int nsel,
                     size_t binsize, float threshold,
                     ap_peak *peaks, int *counts, size_t start, size_t end){
  if(p->pb) return run_pairs_pb(p,d0,nd,t0,nt,tsel,nsel,binsize,threshold,
                                peaks,counts,start,end);
  /* Lanes span templates, not D*T: 32x1 cannot fill one vector. Require
     >=75% occupancy, aligned contiguous templates, and a broad single bin.
     Unmeasured sparse/multi-bin/narrow-window cases keep the original path. */
  if(p->allow_pair_alt && !tsel && nd>=8 && nt>=16 && t0%p->w==0
     && 4*(size_t)nt>=3*((nt+p->w-1)/p->w)*(size_t)p->w
     && end-start>=p->n/2 && binsize>=end-start){
    ap_mf_plan *q=pair_alternate(p,d0,nd,t0,nt);
    if(q) return run_pairs_pb(q,d0,nd,t0,nt,NULL,nt,binsize,threshold,
                             peaks,counts,start,end);
  }
  const size_t n=p->n, nb=(end-start+binsize-1)/binsize;
  /* Tile the pair loop.  Running d outer already keeps one data spectrum resident
     across the t loop, but every template then streams once per d: D*(1+T)
     spectrum reads.  A tile of nd x nt reads nd+nt spectra and does nd*nt pairs,
     so the count falls to (D/nd)(T/nt)(nd+nt).  Tile size is bounded by how many
     spectra fit - each is 2n floats - and there is no point tiling at all once
     two of them fill the cache.

     Measured at 16x16: 2^12 3.40 -> 2.98 (tile 8), 2^14 12.96 -> 12.34, 2^16
     within noise once two spectra fill L2.  8 is never worse, so take it. */
  const int tile = p->tile;
  int total=0;
  for(int dt=0;dt<nd;dt+=tile) for(int tt=0;tt<nsel;tt+=tile){
   const int dend=(nd-dt<tile)?nd:dt+tile, tend=(nsel-tt<tile)?nsel:tt+tile;
   for(int d=dt;d<dend;d++){
    const float *Dr=p->dre+(size_t)(d0+d)*n, *Di=p->dim+(size_t)(d0+d)*n;
    for(int j=tt;j<tend;j++){
      const int t = tsel ? tsel[j] : j;
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
      /* The interpolation block that stood here was unreachable: p->ihlo is
         set only by ap_mf_set_interp, and interpolation is not exposed to
         Python at all, so it was permanently NULL. It was a remnant of the
         U / oversample design, removed at the Python and hmf.c level and
         left behind in the innermost pair loop. */
      if(counts) counts[row]=c;
      total += c;
    }
   }
  }
  return total;
}

int ap_mf_run(ap_mf_plan *p, int d0, int nd, int t0, int nt,
              size_t binsize, float threshold,
              ap_peak *peaks, int *counts, size_t start, size_t end){
  if(!p||nd<1||nt<1||!binsize) return 0;
  if(d0<0||d0+nd>p->nd||t0<0||t0+nt>p->nt) return -1;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  return run_pairs(p,d0,nd,t0,nt,NULL,nt,binsize,threshold,
                   peaks,counts,start,end);
}

/* Filter a time series over a caller-supplied block layout.
 *
 * The flat twin of ap_hmf_run_series, and it exists for the same reason: one
 * call per segment rather than one per block removes the per-block round trip
 * -- no separately planned forward transform, no spectrum handed back and
 * forth. Until now only the hierarchical filter could express this, which made
 * the wide interface unavailable to exactly the callers most likely to want
 * it: flat needs no reference spectrum and no (n, snr, fd) tables, so it is
 * what a non-gravitational-wave domain reaches for.
 *
 * Blocks sharing a window are filtered together, up to the plan's own nd.
 * That is the grouping knob and there is no other: a flat plan's ndata is
 * already how many segments it can hold, so inventing a second control would
 * let the two disagree.
 */
int ap_mf_run_series(ap_mf_plan *p,
                     const float *series,size_t nseries,
                     const size_t *start,const size_t *win_start,
                     const size_t *win_end,int nblocks,
                     int t0,int nt,size_t binsize,float threshold,
                     ap_peak *peaks,int *counts){
  if(!p||nblocks<1||nt<1||!binsize) return 0;
  if(!series||!start||!win_start||!win_end) return -1;
  if(t0<0||t0+nt>p->nt) return -1;
  const size_t n=p->n;
  if(!p->sfwd){
    p->sfwd=ap_alloc64(2*n*sizeof(float));
    p->sspec=ap_alloc64(2*n*sizeof(float));
    if(!p->sfwd||!p->sspec) return -1;
  }
  const size_t nb0=ap_mf_nbins(p,binsize,win_start[0],win_end[0]);
  int total=0;
  for(int b0=0;b0<nblocks;){
    int g=1;
    while(g<p->nd && b0+g<nblocks
          && win_start[b0+g]==win_start[b0] && win_end[b0+g]==win_end[b0]) g++;
    for(int j=0;j<g;j++){
      const size_t s0=start[b0+j];
      size_t have = s0<nseries ? nseries-s0 : 0;
      if(have>n) have=n;
      /* The caller's convention of pre-dividing the block spectrum by n is
         kept, and applied on the way IN so it folds into a copy that has to
         happen anyway. n is a power of two, so 1/n is exact and the transform
         is linear: scaling before is bit-for-bit scaling after. */
      { const float inv=1.0f/(float)n;
        const float *src=series+2*s0;
        for(size_t k=0;k<2*have;k++) p->sfwd[k]=src[k]*inv; }
      if(have<n) memset(p->sfwd+2*have,0,2*(n-have)*sizeof(float));
      ap_fft(p->fft,p->sfwd,p->sspec,AP_FORWARD);
      if(ap_mf_set_data(p,j,p->sspec)) return -1;
    }
    size_t nb=ap_mf_nbins(p,binsize,win_start[b0],win_end[b0]);
    /* peaks is addressed at a single stride, so every window must produce the
       same bin count. A shorter one at a segment's edge does not: it writes
       where the next block's row begins and runs off the end of the caller's
       buffer -- heap corruption from ordinary overlap-save input, since edge
       blocks are exactly the ragged ones this call exists to accept.
       Refusing is the honest answer; the shape the API returns has one nbins
       in it and cannot express two. */
    if(nb!=nb0) return -1;
    int r=ap_mf_run(p,0,g,t0,nt,binsize,threshold,
                    peaks+(size_t)b0*nt*nb,counts?counts+(size_t)b0*nt:NULL,
                    win_start[b0],win_end[b0]);
    if(r<0) return -1;
    total+=r;
    b0+=g;
  }
  return total;
}

int ap_mf_run_sel(ap_mf_plan *p, int d0, int nd, int t0, int nt,
                  const int *tsel, int nsel,
                  size_t binsize, float threshold,
                  ap_peak *peaks, int *counts, size_t start, size_t end){
  if(!p||nd<1||nsel<1||!binsize) return 0;
  if(d0<0||d0+nd>p->nd||t0<0||t0+nt>p->nt) return -1;
  for(int j=0;j<nsel;j++) if(tsel[j]<0||tsel[j]>=nt) return -1;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  return run_pairs(p,d0,nd,t0,nt,tsel,nsel,binsize,threshold,
                   peaks,counts,start,end);
}

/* Debug accessor: how many data slots the plan actually has. */
int ap_mf_ndata(const ap_mf_plan *p){ return p ? p->nd : -1; }
