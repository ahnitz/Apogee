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

/* ---- batched matched filter -----------------------------------------------
   D data segments against T template segments, all length n.  For every pair,

       z[k] = IFFT( FFT(data_d)[f] * conj(FFT(tmpl_t)[f]) )[k]

   and the same peak report as pf_binmax: the loudest sample per bin of the
   search window, with a detection floor.

   Reuse is the point.  Each segment is transformed once at ingest and stored in
   the layout the pair loop wants, so the D*T pair loop never repeats work that
   depends on only one side.  Forward transforms are D+T; pair work is D*T.

   Peaks for pair (d,t) land at peaks[((d-d0)*nt + (t-t0)) * nbins], dense and
   indexed by bin exactly as pf_binmax.  counts, if given, holds one crossing
   count per pair in the same order. */
typedef struct pf_mf_plan pf_mf_plan;

pf_mf_plan *pf_mf_create(size_t n, int ndata, int ntmpl);
void        pf_mf_destroy(pf_mf_plan *p);
size_t      pf_mf_nbins(const pf_mf_plan *p, size_t binsize, size_t start, size_t end);

/* Ingest.  seg is n interleaved complex float32.  Returns 0, or -1 on error. */
int pf_mf_set_data    (pf_mf_plan *p, int d, const float *seg);
int pf_mf_set_template(pf_mf_plan *p, int t, const float *tmpl);

/* Run the pairs [d0,d0+nd) x [t0,t0+nt).  Any sub-block must give the same
   answer as the corresponding slice of the whole, which is what makes tiling
   safe to tune.  Returns total crossings, or -1. */
int pf_mf_run(pf_mf_plan *p, int d0, int nd, int t0, int nt,
              size_t binsize, float threshold,
              pf_peak *peaks, int *counts, size_t start, size_t end);

/* ---- binned maximum -------------------------------------------------------
   The search window [start,end) is cut into bins of `binsize` output samples and
   the loudest member of each bin is reported.  This is the shape a matched-filter
   search actually wants: one candidate per stretch of the spectrum, rather than K
   winners that might all sit in the same place.

   It is also cheaper than top-K.  A per-bin running maximum is a vector max and
   an index blend with no branches, no heap and no final sort - where the top-K
   path has an unpredictable branch per block and a heap push per candidate.

   nbins = ceil((end-start)/binsize); pf_nbins() computes it.  peaks must hold
   B*nbins entries: bin j of transform b lands at peaks[b*nbins + j], in
   increasing frequency, so the output is dense and indexable without a search.

   A bin whose maximum does not exceed `threshold` is reported with index -1 and
   magnitude 0 rather than being dropped, so bin j stays at slot j.  counts[b]
   receives how many bins in transform b did cross; counts may be NULL.

   Pass threshold 0 to report every bin's maximum.

   Returns the total number of crossings across the batch, or -1 on error. */
size_t pf_nbins(const pf_plan *p, size_t binsize, size_t start, size_t end);

/* As pf_binmax for a single transform, but the input is already split into
   separate real and imaginary arrays.  Saves the deinterleave for callers that
   naturally hold data that way - the matched filter forms its products directly
   into split arrays. */
int pf_binmax_split(pf_plan *p, const float *re, const float *im,
                    size_t binsize, float threshold, pf_peak *peaks, int *count,
                    int sign, size_t start, size_t end);

/* Binned maximum of the matched-filter product, with the product formed inside
   the transform's load so it never reaches memory.  Returns -1 if the selected
   back end has no fused path for this length, in which case form the product and
   call pf_binmax_split. */
/* SIMD lane width of the active back end (8 or 16), or 0 if unsupported. */
int pf_lane_width(void);

int pf_binmax_prod(pf_plan *p, const float *dr, const float *di,
                   const float *tr, const float *ti,
                   size_t binsize, float threshold, pf_peak *peaks, int *count,
                   int sign, size_t start, size_t end);

int pf_binmax(pf_plan *p, const float *in, size_t dist, int B,
              size_t binsize, float threshold, pf_peak *peaks, int *counts,
              int sign, size_t start, size_t end);

int pf_topk_window(pf_plan *p, const float *in, int K, pf_peak *peaks, int sign,
                   size_t start, size_t end);

#ifdef __cplusplus
}
#endif
#endif
