/* apogee - single-threaded batched matched filter with peak-only output.
 *
 * Correlate D data segments against T templates and get back, for each pair, the
 * loudest sample in each bin of a search window.  The full correlation output is
 * never formed.
 *
 * Inputs are FREQUENCY DOMAIN: the unnormalised forward transform of each
 * segment, natural order, interleaved complex float32.  Lengths supported are
 * 1024 and the powers of two from 4096 to 2^20.
 *
 * Correlation is circular; zero-pad before ingest for linear.  The inverse is
 * unnormalised, matching FFTW and MKL, so a perfect match returns n * energy.
 *
 * There is no plan object to manage beyond the filter itself: ap_mf_plan holds
 * everything, is built once, and is reused for every pair.
 */
#ifndef APOGEE_H
#define APOGEE_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif

/* Transform direction, only needed by the internal transform API. */
#define AP_FORWARD  (-1)
#define AP_BACKWARD (+1)

/* One peak: where it is, and what the transform's value there is. */
typedef struct {
    long  index;      /* bin index k, in [0, N)                      */
    float re, im;     /* X[k]                                        */
    float magnitude;  /* |X[k]| = sqrt(re*re + im*im)                */
} ap_peak;

/* ---- batched matched filter -----------------------------------------------
   D data segments against T template segments, all length n.  For every pair,

       z[k] = IFFT( FFT(data_d)[f] * conj(FFT(tmpl_t)[f]) )[k]

   and the same peak report as ap_binmax: the loudest sample per bin of the
   search window, with a detection floor.

   Segments are supplied ALREADY TRANSFORMED - the caller's pipeline has them in
   the frequency domain anyway, and D+T forward transforms have no business
   inside a D*T loop.  Ingest here only rearranges: templates are conjugated, and
   both sides are stored in the layout stage A walks, which is what lets every
   one of the D*T pair transforms read sequentially.  That rearrangement is paid
   once per segment, so it stays amortised however many pairs run.

   Peaks for pair (d,t) land at peaks[((d-d0)*nt + (t-t0)) * nbins], dense and
   indexed by bin exactly as ap_binmax.  counts, if given, holds one crossing
   count per pair in the same order. */
typedef struct ap_mf_plan ap_mf_plan;

ap_mf_plan *ap_mf_create(size_t n, int ndata, int ntmpl);
void        ap_mf_destroy(ap_mf_plan *p);
size_t      ap_mf_nbins(const ap_mf_plan *p, size_t binsize, size_t start, size_t end);

/* Ingest.  spec is the segment's SPECTRUM: n interleaved complex float32, the
   unnormalised forward transform of the segment, in natural frequency order.
   Returns 0, or -1 on error. */
int ap_mf_set_data    (ap_mf_plan *p, int d, const float *spec);
int ap_mf_set_template(ap_mf_plan *p, int t, const float *spec);

/* Run the pairs [d0,d0+nd) x [t0,t0+nt).  Any sub-block must give the same
   answer as the corresponding slice of the whole, which is what makes tiling
   safe to tune.  Returns total crossings, or -1. */
int ap_mf_run(ap_mf_plan *p, int d0, int nd, int t0, int nt,
              size_t binsize, float threshold,
              ap_peak *peaks, int *counts, size_t start, size_t end);

/* Is this length supported?  1024, and the powers of two from 4096 to 2^20. */
int ap_supported(size_t n);

/* Which back end the CPU selected: "avx512", "avx2", or "unsupported". */
const char *ap_isa(void);

#ifdef __cplusplus
}
#endif
#endif
