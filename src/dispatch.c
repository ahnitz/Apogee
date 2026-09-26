/* matchedfilter: public API over whichever kernel Highway's runtime dispatch
 * selected.  Nothing here is target-specific, so it compiles at the baseline
 * and is safe to execute before the CPU has been interrogated.
 *
 * Set MF_ISA to a Highway target name -- SSE4, AVX2, AVX3, NEON, EMU128 --
 * to narrow the choice; `matchedfilter.backend()` reports what was picked.
 */
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <time.h>
#include <math.h>
#include "matchedfilter.h"
#include "transform.h"
#include "backend.h"

struct ap_plan { const ap_backend *be; void *h; size_t n; };

#define pick() ap_backend_active()

const char *ap_isa(void){ const ap_backend *b=pick(); return b?b->name:"unsupported"; }

int ap_supported(size_t N){
  const ap_backend *b=pick();
  return b && b->supported(N);
}

ap_plan *ap_create(size_t N){
  const ap_backend *b=pick();
  if(!b || !b->supported(N)) return NULL;
  void *h=b->create(N);
  if(!h) return NULL;
  ap_plan *p=malloc(sizeof(*p));
  if(!p){ b->destroy(h); return NULL; }
  p->be=b; p->h=h; p->n=N;
  return p;
}

const char *ap_plan_backend(const ap_plan *p){ return p?p->be->name:"none"; }

ap_plan *ap_create_pairbatch(size_t N){
  const ap_backend *b=pick();
  if(!b || N<64 || N>1024 || !b->supported(N) || !b->create_pairbatch) return NULL;
  void *h=b->create_pairbatch(N);
  if(!h) return NULL;
  ap_plan *p=malloc(sizeof(*p));
  if(!p){ b->destroy(h); return NULL; }
  p->be=b; p->h=h; p->n=N;
  return p;
}

void ap_destroy(ap_plan *p){
  if(!p) return;
  p->be->destroy(p->h);
  free(p);
}

void ap_fft(ap_plan *p,const float *in,float *out,int sign){
  p->be->fft(p->h,in,out,sign==AP_BACKWARD);
}

size_t ap_nbins(const ap_plan *p,size_t binsize,size_t start,size_t end){
  if(!p||!binsize) return 0;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  return (end-start+binsize-1)/binsize;
}

/* split-input binned max, for callers that already hold re/im apart */
int ap_binmax_split(ap_plan *p,const float *re,const float *im,
                    size_t binsize,float threshold,ap_peak *peaks,int *count,
                    int sign,size_t start,size_t end){
  if(!p||!binsize) return -1;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  if(!p->be->binmax_split) return -1;
  const size_t nb=(end-start+binsize-1)/binsize;
  if(p->be->binmax_split(p->h,re,im,binsize,threshold,peaks,sign==AP_BACKWARD,start,end)<0)
    return -1;
  int c=0; for(size_t j=0;j<nb;j++) if(peaks[j].index>=0) c++;
  if(count) *count=c;
  return c;
}

/* matched-filter product fused into the transform's load; -1 if unavailable */
int ap_plan_split(const ap_plan *p,int *n1,int *n2){
  if(!p||!p->be->split) return 0;
  return p->be->split(p->h,n1,n2);
}

int ap_has_fused_prod(const ap_plan *p){
  if(!p||!p->be->has_prod||!p->be->binmax_prod) return 0;
  return p->be->has_prod(p->h);
}

int ap_plan_pairbatch(const ap_plan *p){
  if(!p||!p->be->pairbatch||!p->be->binmax_prod_batch) return 0;
  return p->be->pairbatch(p->h);
}

int ap_plan_broadcast_data(const ap_plan *p){
  return p && p->be->broadcast_data && p->be->broadcast_data(p->h);
}

int ap_binmax_prod_batch(ap_plan *p,const float *dr,const float *di,
                         const float *tr,const float *ti,int nlane,
                         size_t binsize,float threshold,ap_peak *peaks,
                         int *counts,int sign,size_t start,size_t end){
  if(!p||!binsize||nlane<1) return -1;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  if(!p->be->binmax_prod_batch) return -1;
  const size_t nb=(end-start+binsize-1)/binsize;
  if(p->be->binmax_prod_batch(p->h,dr,di,tr,ti,nlane,binsize,threshold,peaks,
                              sign==AP_BACKWARD,start,end)<0) return -1;
  int total=0;
  for(int l=0;l<nlane;l++){
    int c=0;
    for(size_t j=0;j<nb;j++) if(peaks[(size_t)l*nb+j].index>=0) c++;
    if(counts) counts[l]=c;
    total+=c;
  }
  return total;
}

int ap_binmax_prod(ap_plan *p,const float *dr,const float *di,
                   const float *tr,const float *ti,
                   size_t binsize,float threshold,ap_peak *peaks,int *count,
                   int sign,size_t start,size_t end){
  if(!p||!binsize) return -1;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  if(!p->be->binmax_prod) return -1;
  const size_t nb=(end-start+binsize-1)/binsize;
  if(p->be->binmax_prod(p->h,dr,di,tr,ti,binsize,threshold,peaks,
                        sign==AP_BACKWARD,start,end)<0) return -1;
  int c=0; for(size_t j=0;j<nb;j++) if(peaks[j].index>=0) c++;
  if(count) *count=c;
  return c;
}

float ap_interp_max(ap_plan *p,size_t ws,size_t we,float evmax,
                    const float *hlo,const float *hhi,int K,int ncand,float frac){
  if(!p||!p->be->interp) return evmax;
  return p->be->interp(p->h,ws,we,evmax,hlo,hhi,K,ncand,frac);
}

size_t ap_series_stride(ap_plan *p){
  if(!p||!p->be->series_stride) return 0;
  return p->be->series_stride(p->h);
}

float *ap_series_buf(ap_plan *p,int on){
  if(!p||!p->be->series) return NULL;
  return p->be->series(p->h,on);
}

int ap_binmax(ap_plan *p,const float *in,size_t dist,int B,
              size_t binsize,float threshold,ap_peak *peaks,int *counts,
              int sign,size_t start,size_t end){
  if(B<1||!binsize) return 0;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  if(!p->be->binmax) return -1;
  const size_t nb=(end-start+binsize-1)/binsize;
  const int conj = sign==AP_BACKWARD;
  int total=0;
  for(int b=0;b<B;b++){
    ap_peak *o=peaks+(size_t)b*nb;
    if(p->be->binmax(p->h,in+2*(size_t)b*dist,binsize,threshold,o,conj,start,end)<0)
      return -1;
    int c=0;
    for(size_t j=0;j<nb;j++) if(o[j].index>=0) c++;
    if(counts) counts[b]=c;
    total+=c;
  }
  return total;
}


/* SIMD lane width of the active back end, so callers that want to store data
   in the layout stage A walks can compute it.  0 if unsupported.

   This used to be a chain of pointer comparisons against the named back ends,
   and got it wrong once: written as "bal8 ? 8 : 16" it told the portable back
   end it had 16 lanes, the matched filter stored every spectrum group-major
   for the wrong width, the transforms still agreed, and only the correlation
   came out wrong. */
int ap_lane_width(void){
  const ap_backend *b=pick();
  return b?b->lanes:0;
}
