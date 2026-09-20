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
  int   (*topk)(void *, const float *in, int K, pf_peak *out, int conj,
                size_t start, size_t end);
  int   (*supported)(size_t N);
  /* pre-quantised input path; qhi/qlo/qs may be NULL to mean "plain fp32 in" */
  int   (*topk_q)(void *, const short *qhi, const signed char *qlo, const float *qs,
                  int K, pf_peak *out, int conj, size_t start, size_t end);
  void  (*quantize)(void *, const float *in, short *qhi, signed char *qlo, float *qs);
} pf_backend;
extern const pf_backend pf_be_avx512;   /* specialised: 1024 kernel + tuned 2^17..2^20 */
extern const pf_backend pf_be_bal8;    /* width-generic balanced split, 8 lanes (AVX2)  */
extern const pf_backend pf_be_bal16;   /* same source at 16 lanes, for cross-checking  */
#endif
