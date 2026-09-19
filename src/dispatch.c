/* peakfft: public API and runtime ISA selection.
 *
 * Compiled for the baseline ISA only - it must be safe to execute before we know
 * what the CPU supports, so nothing here may use AVX intrinsics.
 *
 * Set PEAKFFT_ISA to force a back end for testing:
 *   avx512       specialised AVX-512 paths (default when supported)
 *   avx2         width-generic balanced split at 8 lanes
 *   balanced512  the same generic source at 16 lanes (cross-check)
 */
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "peakfft.h"
#include "backend.h"

struct pf_plan { const pf_backend *be; void *h; size_t n; };

static int have_avx512(void){
  return __builtin_cpu_supports("avx512f") && __builtin_cpu_supports("avx512dq")
      && __builtin_cpu_supports("avx512bw") && __builtin_cpu_supports("avx512vl");
}
static int have_avx2(void){
  return __builtin_cpu_supports("avx2") && __builtin_cpu_supports("fma");
}

static const pf_backend *pick(void){
  const char *e = getenv("PEAKFFT_ISA");
  if(e && *e){
    if(!strcmp(e,"avx512"))      return have_avx512() ? &pf_be_avx512 : NULL;
    if(!strcmp(e,"avx2"))        return have_avx2()   ? &pf_be_bal8   : NULL;
    if(!strcmp(e,"balanced512")) return have_avx512() ? &pf_be_bal16  : NULL;
    fprintf(stderr,"peakfft: unknown PEAKFFT_ISA=\"%s\" (avx512|avx2|balanced512)\n",e);
    return NULL;
  }
  if(have_avx512()) return &pf_be_avx512;
  if(have_avx2())   return &pf_be_bal8;
  return NULL;
}

const char *pf_isa(void){ const pf_backend *b=pick(); return b?b->name:"unsupported"; }

int pf_supported(size_t N){
  const pf_backend *b=pick();
  return b && b->supported(N);
}

pf_plan *pf_create(size_t N){
  const pf_backend *b=pick();
  if(!b || !b->supported(N)) return NULL;
  void *h=b->create(N);
  if(!h) return NULL;
  pf_plan *p=malloc(sizeof(*p));
  if(!p){ b->destroy(h); return NULL; }
  p->be=b; p->h=h; p->n=N;
  return p;
}

void pf_destroy(pf_plan *p){
  if(!p) return;
  p->be->destroy(p->h);
  free(p);
}

void pf_fft(pf_plan *p,const float *in,float *out,int sign){
  p->be->fft(p->h,in,out,sign==PF_BACKWARD);
}

int pf_topk(pf_plan *p,const float *in,int K,pf_peak *peaks,int sign){
  if(K<1) return 0;
  if(K>PF_MAX_K) K=PF_MAX_K;
  return p->be->topk(p->h,in,K,peaks,sign==PF_BACKWARD);
}
