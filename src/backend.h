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
  int   (*topk)(void *, const float *in, int K, pf_peak *out, int conj);
  int   (*supported)(size_t N);
} pf_backend;
extern const pf_backend pf_be_avx512;   /* specialised: 1024 kernel + tuned 2^17..2^20 */
extern const pf_backend pf_be_bal8;    /* width-generic balanced split, 8 lanes (AVX2)  */
extern const pf_backend pf_be_bal16;   /* same source at 16 lanes, for cross-checking  */
#endif
