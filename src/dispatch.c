/* matchedfilter: public API and runtime ISA selection.
 *
 * Compiled for the baseline ISA only - it must be safe to execute before we know
 * what the CPU supports, so nothing here may use AVX intrinsics.
 *
 * Set MF_ISA to force a back end for testing:
 *   avx512       specialised AVX-512 paths (default when supported)
 *   avx2         width-generic balanced split at 8 lanes
 *   balanced512  the same generic source at 16 lanes (cross-check)
 *   portable     the same source again, compiler-vectorised rather than
 *                hand-written; the best build the CPU supports
 *   highway      the same source on Google Highway, if built with it
 *   portable1    that source built for AVX only (Sandy/Ivy Bridge)
 *   portable0    that source at baseline, the fallback for an x86 without AVX
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

/* Whether the x86 kernels are available is a property of the BUILD, not of
   the slice being compiled.  A macOS universal2 build compiles this file once
   per architecture from one source set: the arm64 slice must not reference
   back ends that were never compiled, and neither must the x86_64 slice of a
   build that chose the portable set.  setup.py decides and says so. */
/* __builtin_cpu_supports is x86-only, and so is everything it guards. */
#if (defined(__x86_64__) || defined(__i386__)) && !defined(AP_NO_WIDE_KERNELS)
#define AP_HAVE_X86 1
static int have_avx512(void){
  return __builtin_cpu_supports("avx512f") && __builtin_cpu_supports("avx512dq")
      && __builtin_cpu_supports("avx512bw") && __builtin_cpu_supports("avx512vl");
}
static int have_avx2(void){
  return __builtin_cpu_supports("avx2") && __builtin_cpu_supports("fma");
}
#else
#define AP_HAVE_X86 0
#endif

static const ap_backend *widest(void){
#if AP_HAVE_X86
  if(have_avx512()) return &ap_be_hwy16;
  if(have_avx2())   return &ap_be_hwy8;
#endif
  return &ap_be_hwy4;
}

static const ap_backend *pick(void){
  const char *e = getenv("MF_ISA");
  if(!e || !*e)              return widest();
  if(!strcmp(e,"highway"))   return widest();
  if(!strcmp(e,"highway4"))  return &ap_be_hwy4;
#if AP_HAVE_X86
  if(!strcmp(e,"highway8"))  return have_avx2()   ? &ap_be_hwy8  : NULL;
  if(!strcmp(e,"highway16")) return have_avx512() ? &ap_be_hwy16 : NULL;
#endif
  fprintf(stderr,"matchedfilter: unknown or unavailable MF_ISA=\"%s\"\n", e);
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
int ap_plan_split(const ap_plan *p,int *n1,int *n2){
  if(!p||!p->be->split) return 0;
  return p->be->split(p->h,n1,n2);
}

int ap_has_fused_prod(const ap_plan *p){
  if(!p||!p->be->has_prod||!p->be->binmax_prod) return 0;
  return p->be->has_prod(p->h);
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
   the layout stage A walks can compute it.  0 if unsupported.

   This has to name every 8-lane back end explicitly.  Written as "bal8 ? 8 : 16"
   it silently told the portable back end it had 16 lanes, and the matched
   filter then stored every spectrum group-major for the wrong width -- the
   transforms still agreed, and only the correlation came out wrong. */
int ap_lane_width(void){
  const ap_backend *b=pick();
  if(!b) return 0;
  if(b==&ap_be_hwy16) return 16;
  if(b==&ap_be_hwy8)  return 8;
  return 4;
}
