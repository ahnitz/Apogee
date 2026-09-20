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
#include <time.h>
#include <math.h>
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

const char *pf_plan_backend(const pf_plan *p){ return p?p->be->name:"none"; }

void pf_destroy(pf_plan *p){
  if(!p) return;
  p->be->destroy(p->h);
  free(p);
}

void pf_fft(pf_plan *p,const float *in,float *out,int sign){
  p->be->fft(p->h,in,out,sign==PF_BACKWARD);
}

/* One scale per block of 16 complex; the 24-bit value is split hi16 / lo8. */
#define PF_QBLK 16
int pf_qinput_alloc(pf_plan *p,pf_qinput *q){
  size_t n=p->n;
  q->n=n;
  q->hi   = aligned_alloc(64, n*2*sizeof(short));
  q->lo   = aligned_alloc(64, n*2);
  q->scale= aligned_alloc(64, (n/PF_QBLK)*sizeof(float)+64);
  if(!q->hi||!q->lo||!q->scale){ pf_qinput_free(q); return -1; }
  return 0;
}
void pf_qinput_free(pf_qinput *q){
  if(!q) return;
  free(q->hi); free(q->lo); free(q->scale);
  q->hi=NULL; q->lo=NULL; q->scale=NULL;
}
void pf_qinput_fill(pf_plan *p,pf_qinput *q,const float *in){
  if(p->be->quantize) p->be->quantize(p->h,in,q->hi,q->lo,q->scale);
}
int pf_topk_q(pf_plan *p,const pf_qinput *q,int K,pf_peak *peaks,int sign,
              size_t start,size_t end){
  if(K<1) return 0;
  if(K>PF_MAX_K) K=PF_MAX_K;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  if(!p->be->topk_q) return -1;
  return p->be->topk_q(p->h,q->hi,q->lo,q->scale,K,peaks,sign==PF_BACKWARD,start,end);
}

int pf_topk_window(pf_plan *p,const float *in,int K,pf_peak *peaks,int sign,
                   size_t start,size_t end){
  if(K<1) return 0;
  if(K>PF_MAX_K) K=PF_MAX_K;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  return p->be->topk(p->h,in,K,peaks,sign==PF_BACKWARD,start,end);
}

int pf_topk(pf_plan *p,const float *in,int K,pf_peak *peaks,int sign){
  return pf_topk_window(p,in,K,peaks,sign,0,p->n);
}
