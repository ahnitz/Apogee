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
  int   (*supported)(size_t N);
  /* binned maximum; writes exactly nbins dense entries */
  int   (*binmax)(void *, const float *in, size_t binsize, float thr,
                  pf_peak *out, int conj, size_t start, size_t end);
  /* Same, but the input is already split into re/im.  Two contract differences
     that exist to keep the matched filter's pair loop free of copies:
       - re/im are CONSUMED IN PLACE and left undefined on return;
       - the input is NOT conjugated for a backward transform.  The caller folds
         that into however it produced the data (for a product it is free), and
         conj here only sets the sign of the reported imaginary parts. */
  int   (*binmax_split)(void *, const float *re, const float *im, size_t binsize,
                        float thr, pf_peak *out, int conj, size_t start, size_t end);
  /* matched filter: form conj(D*T) inside stage A's load, so the product never
     reaches memory.  Inputs are read-only here, unlike binmax_split. */
  int   (*binmax_prod)(void *, const float *dr, const float *di,
                       const float *tr, const float *ti, size_t binsize,
                       float thr, pf_peak *out, int conj, size_t start, size_t end);
} pf_backend;
extern const pf_backend pf_be_avx512;   /* specialised: 1024 kernel + tuned 2^17..2^20 */
extern const pf_backend pf_be_bal8;    /* width-generic balanced split, 8 lanes (AVX2)  */
extern const pf_backend pf_be_bal16;   /* same source at 16 lanes, for cross-checking  */
#endif
