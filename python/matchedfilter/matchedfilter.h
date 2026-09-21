/* matchedfilter - single-threaded batched matched filter with peak-only output.
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
#ifndef MATCHEDFILTER_H
#define MATCHEDFILTER_H
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
/* ---------------------------------------------------------------------------
 * Hierarchical matched filter.
 *
 * Most of a template's signal-to-noise sits in the low part of the band.  This
 * filter correlates only that part, on a coarse lag grid, and pays for the full
 * correlation only where the coarse result could plausibly become a detection.
 *
 * The guarantee is one-sided and exact: every peak this reports is bit-identical
 * to what ap_mf_run would report for the same inputs.  It never invents a peak
 * and never shifts one.  What it can do is MISS a peak, at a rate bounded by the
 * false-dismissal target given at construction.  If that trade is not acceptable,
 * use ap_mf_run.
 *
 * snr is the |rho| of the weakest signal that must be kept (5 is typical); fd is
 * the tolerated false-dismissal probability for such a signal (1e-2 .. 1e-4).
 * Band, oversampling and tap count come from a compiled-in measured table -
 * matchedfilter does not autotune - and can be overridden for testing with
 * ap_hmf_create_ex.
 */
typedef struct ap_hmf_plan ap_hmf_plan;

ap_hmf_plan *ap_hmf_create(size_t n, int ndata, int ntmpl, float snr, float fd);
ap_hmf_plan *ap_hmf_create_ex(size_t n, int ndata, int ntmpl, float snr, float fd,
                              size_t band, int oversample, int taps);
void         ap_hmf_destroy(ap_hmf_plan *p);

size_t ap_hmf_nbins(const ap_hmf_plan *p, size_t binsize, size_t start, size_t end);
/* Reference SNR distribution: expected power per bin of the filter OUTPUT,
 * length n, real, any scale.  Setting it is usually the right thing to do.
 *
 * By default each template's band fraction and recovery factors are measured
 * from the template itself, which assumes its own power distribution is the
 * distribution of the SNR it produces.  That holds only when the data is white
 * and the template is whitened.  It fails, for instance, when the template is a
 * broadband ratio filter whose output reconstructs a strongly low-frequency
 * signal: the gate would read the filter and be badly wrong.
 *
 * In practice the output distribution is a property of the SIGNAL, not of the
 * individual template, and is near-identical across a bank -- so supply it once
 * here rather than tuning per template.  Doing so also skips the per-template
 * measurement at ingest entirely.
 *
 * Pass NULL to return to measuring each template.  Set before the templates. */
int    ap_hmf_set_reference(ap_hmf_plan *p, const float *power);

int    ap_hmf_set_data    (ap_hmf_plan *p, int d, const float *spec);
int    ap_hmf_set_template(ap_hmf_plan *p, int t, const float *spec);

/* Same arguments and same output layout as ap_mf_run. */
int ap_hmf_run(ap_hmf_plan *p, int d0, int nd, int t0, int nt,
               size_t binsize, float threshold,
               ap_peak *peaks, int *counts, size_t start, size_t end);

/* Filter a time series directly, over a caller-supplied block layout.
 *
 * The caller still owns the overlap-save arithmetic: it decides where each
 * block starts and which span of each block's output is valid.  matchedfilter only
 * executes that plan -- forward transform per block, gate, refine where needed
 * -- which removes the per-block round trip through the caller entirely: no
 * separately-planned forward FFT, no spectrum handed back and forth, and one
 * call per segment instead of one per block.
 *
 * series holds `nseries` complex samples, interleaved.  For block b, the
 * transform covers series[start[b] .. start[b]+n), and the peak search covers
 * lags [win_start[b], win_end[b]) within that block.  Windows are per block, so
 * the ragged ones at a segment's edges need no special handling.
 *
 * peaks is [block][template][bin] with bins as ap_hmf_run.  A block whose
 * transform would run past nseries is zero-padded.
 */
int ap_hmf_run_series(ap_hmf_plan *p,
                      const float *series, size_t nseries,
                      const size_t *start, const size_t *win_start,
                      const size_t *win_end, int nblocks,
                      int t0, int nt, size_t binsize, float threshold,
                      ap_peak *peaks, int *counts);

/* Diagnostics: pairs examined and pairs that went to the full correlation.
   The ratio is the measured trigger rate, which is what the speedup rides on. */
void ap_hmf_stats(const ap_hmf_plan *p, long *pairs, long *triggers);

/* The band / oversampling / taps / gate the table chose, for reporting. */
void ap_hmf_config(const ap_hmf_plan *p, size_t *band, int *oversample, int *taps);

int ap_supported(size_t n);

/* Which back end the CPU selected: "avx512", "avx2", or "unsupported". */
const char *ap_isa(void);

#ifdef __cplusplus
}
#endif
#endif
