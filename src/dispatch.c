/* apogee: public API and runtime ISA selection.
 *
 * Compiled for the baseline ISA only - it must be safe to execute before we know
 * what the CPU supports, so nothing here may use AVX intrinsics.
 *
 * Set APOGEE_ISA to force a back end for testing:
 *   avx512       specialised AVX-512 paths (default when supported)
 *   avx2         width-generic balanced split at 8 lanes
 *   balanced512  the same generic source at 16 lanes (cross-check)
 */
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <time.h>
#include <math.h>
#include "apogee.h"
#include "backend.h"

struct ap_plan { const ap_backend *be; void *h; size_t n; };

static int have_avx512(void){
  return __builtin_cpu_supports("avx512f") && __builtin_cpu_supports("avx512dq")
      && __builtin_cpu_supports("avx512bw") && __builtin_cpu_supports("avx512vl");
}
static int have_avx2(void){
  return __builtin_cpu_supports("avx2") && __builtin_cpu_supports("fma");
}

static const ap_backend *pick(void){
  const char *e = getenv("APOGEE_ISA");
  if(e && *e){
    if(!strcmp(e,"avx512"))      return have_avx512() ? &ap_be_avx512 : NULL;
    if(!strcmp(e,"avx2"))        return have_avx2()   ? &ap_be_bal8   : NULL;
    if(!strcmp(e,"balanced512")) return have_avx512() ? &ap_be_bal16  : NULL;
    fprintf(stderr,"apogee: unknown APOGEE_ISA=\"%s\" (avx512|avx2|balanced512)\n",e);
    return NULL;
  }
  if(have_avx512()) return &ap_be_avx512;
  if(have_avx2())   return &ap_be_bal8;
  return NULL;
}

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


/* SIMD lane width of the active back end, so callers that want to store data in
   the layout stage A walks can compute it.  0 if unsupported. */
int ap_lane_width(void){
  const ap_backend *b=pick();
  if(!b) return 0;
  return (b==&ap_be_bal8) ? 8 : 16;
}
