/* peakfft - single-precision complex FFT specialised for finding the loudest bins.
 *
 * Single-threaded, x86-64 AVX-512.  Forward transform, complex-to-complex, float32.
 *
 * Two entry points:
 *   pf_fft()  - exact full transform, bit-accurate to ~2e-7 relative.
 *   pf_topk() - returns only the K largest-|X| bins.  Much faster at large N because
 *               the output array is never materialised and the bulk of the arithmetic
 *               runs at reduced precision, with the reported bins refined exactly.
 *
 * "Loudest" means largest complex modulus |X[k]| = sqrt(re^2+im^2).
 *
 * Supported sizes: 1024 and 1048576 (2^10, 2^20).  pf_create returns NULL otherwise.
 */
#ifndef PEAKFFT_H
#define PEAKFFT_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct pf_plan pf_plan;

/* Create a plan for transform length N.  Returns NULL if N is unsupported. */
pf_plan *pf_create(size_t N);
void     pf_destroy(pf_plan *p);

/* Exact forward transform.  in/out are interleaved complex float, N elements each.
   out must not alias in.  Both should be 64-byte aligned for best performance. */
void pf_fft(pf_plan *p, const float *in, float *out);

/* Forward transform returning only the K bins with the largest |X|.
   Results are written in descending-|X| order:
     idx[a] = bin index, re[a]/im[a] = the exact complex value at that bin.
   Caller supplies arrays of at least K elements.  K must be <= PF_MAX_K.
   Returns the number of bins written (== K for K <= N). */
#define PF_MAX_K 64
int pf_topk(pf_plan *p, const float *in, int K, int *idx, float *re, float *im);

/* Largest N this build supports, and a query for whether N is supported. */
int pf_supported(size_t N);

#ifdef __cplusplus
}
#endif
#endif
