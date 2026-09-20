#ifndef PF_BACKEND_H
#define PF_BACKEND_H
#include <stddef.h>
#include "peakfft.h"
/* One implementation of the transform, selected at runtime by CPU support. */
typedef struct {
  const char *name;
  void *(*create)(size_t N);
  void  (*destroy)(void *);
  void  (*fft)(void *, const float *in, float *out, int conj);
  /* thr0 is a magnitude floor: bins below it are never candidates.  0 means
     "no floor".  It primes the top-K admission test, which is what makes
     threshold mode faster rather than just a post-filter. */
  int   (*topk)(void *, const float *in, int K, pf_peak *out, int conj,
                size_t start, size_t end, float thr0);
  int   (*supported)(size_t N);
  /* pre-quantised input path; qhi/qlo/qs may be NULL to mean "plain fp32 in" */
  int   (*topk_q)(void *, const short *qhi, const signed char *qlo, const float *qs,
                  int K, pf_peak *out, int conj, size_t start, size_t end, float thr0);
  void  (*quantize)(void *, const float *in, short *qhi, signed char *qlo, float *qs);
  /* binned maximum; writes exactly nbins dense entries */
  int   (*binmax)(void *, const float *in, size_t binsize, float thr,
                  pf_peak *out, int conj, size_t start, size_t end);
} pf_backend;
extern const pf_backend pf_be_avx512;   /* specialised: 1024 kernel + tuned 2^17..2^20 */
extern const pf_backend pf_be_bal8;    /* width-generic balanced split, 8 lanes (AVX2)  */
extern const pf_backend pf_be_bal16;   /* same source at 16 lanes, for cross-checking  */
#endif
