/* peakfft - single-precision complex FFT specialised for finding the loudest bins.
 *
 * Single-threaded, x86-64 AVX-512.  Complex-to-complex, float32, forward and
 * backward.  Sizes 1024 and 4096 .. 1048576 (2^10, 2^12 .. 2^20).
 *
 * "Loudest" means largest complex modulus |X[k]| = sqrt(re^2 + im^2).
 *
 * Sign convention matches FFTW and MKL:
 *   PF_FORWARD   X[k] = sum_n x[n] exp(-2*pi*i*n*k/N)
 *   PF_BACKWARD  X[k] = sum_n x[n] exp(+2*pi*i*n*k/N)
 * Neither direction applies a 1/N scale, so a forward followed by a backward
 * transform multiplies the input by N.
 */
#ifndef PEAKFFT_H
#define PEAKFFT_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif

#define PF_FORWARD  (-1)
#define PF_BACKWARD (+1)

/* Largest K that pf_topk will return. */
#define PF_MAX_K 64

/* One peak: where it is, and what the transform's value there is. */
typedef struct {
    long  index;      /* bin index k, in [0, N)                      */
    float re, im;     /* X[k]                                        */
    float magnitude;  /* |X[k]| = sqrt(re*re + im*im)                */
} pf_peak;

typedef struct pf_plan pf_plan;

/* Create a plan for transform length N.  Returns NULL if N is unsupported.
   One plan serves both directions. */
pf_plan *pf_create(size_t N);
void     pf_destroy(pf_plan *p);
int      pf_supported(size_t N);

/* Name of the back end that will be used: "avx512", "avx2", or "unsupported".
   Override with the PEAKFFT_ISA environment variable (see README). */
const char *pf_isa(void);

/* Name of the back end this plan actually selected (autotuning may pick a
   different one from pf_isa() for large N). */
const char *pf_plan_backend(const pf_plan *p);

/* Full transform.  in/out are interleaved complex float, N elements each;
   out must not alias in.  64-byte alignment is best.  sign is PF_FORWARD or
   PF_BACKWARD.  Mainly a reference and test hook - pf_topk is the fast path. */
void pf_fft(pf_plan *p, const float *in, float *out, int sign);

/* Transform returning only the K loudest bins, in descending |X| order.
   peaks must have room for K entries; K is clamped to PF_MAX_K.
   Returns the number written.  The output array is never materialised. */
int pf_topk(pf_plan *p, const float *in, int K, pf_peak *peaks, int sign);

/* ---- pre-quantised input ------------------------------------------------
   The input read is the one cost the top-K structure could never remove: it is
   8 MiB of fp32 at N=2^20 and must all be touched.  If the producer can store
   the data in reduced form instead, that read shrinks.

   pf_qinput holds the input as 24-bit block floating point (blocks of 16 complex):
   6 bytes per complex instead of 8, so the read drops by a quarter.  Accuracy is
   ~2e-8 relative, i.e. essentially free - unlike a 16-bit form, which would cost
   ~5e-6 and is irreversible, since no refinement can recover detail the input
   never carried.

   pf_qinput_fill() is a convenience for benchmarking and testing; in real use the
   producer would write this format directly and the fp32 array would never exist. */
typedef struct {
  short       *hi;    /* high 16 bits, [block][16 re | 16 im] */
  signed char *lo;    /* low 8 bits, same layout              */
  float       *scale; /* one per block of 16 complex          */
  size_t       n;
} pf_qinput;

int  pf_qinput_alloc(pf_plan *p, pf_qinput *q);
void pf_qinput_free(pf_qinput *q);
void pf_qinput_fill(pf_plan *p, pf_qinput *q, const float *in);
int  pf_topk_q(pf_plan *p, const pf_qinput *q, int K, pf_peak *peaks, int sign,
               size_t start, size_t end);

/* As pf_topk, but only bins with start <= k < end are considered.  Indices in
   the result are still absolute (relative to the whole transform), not relative
   to the window.  start/end are clamped to [0, N]; start >= end returns 0.
   Outputs outside the window are never even tested, so a narrower window is
   slightly cheaper - the transform itself still costs the same. */
int pf_topk_window(pf_plan *p, const float *in, int K, pf_peak *peaks, int sign,
                   size_t start, size_t end);

#ifdef __cplusplus
}
#endif
#endif
