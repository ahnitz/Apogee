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
int         ap_mf_ndata(const ap_mf_plan *p);
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

/* Same, but for a scattered set of templates: tsel[0..nsel) are local indices
   into [0,nt).  Rows are still addressed by the local index, so the skipped
   ones are left as the caller set them.  This exists because the hierarchical
   filter's second stage runs whichever templates fired, and one call per
   template re-reads the data spectrum every time. */
int ap_mf_run_sel(ap_mf_plan *p, int d0, int nd, int t0, int nt,
                  const int *tsel, int nsel,
                  size_t binsize, float threshold,
                  ap_peak *peaks, int *counts, size_t start, size_t end);

/* Filter a time series over a caller-supplied block layout: block b covers
   series[start[b] ...] and reports lags [win_start[b], win_end[b]).  Windows
   are per block, so the ragged ones at a segment's edges need no grouping.

   peaks is [block][template][bin] with bins as ap_mf_run.  A block whose
   transform would run past nseries is zero-padded.  Blocks sharing a window
   are filtered together, up to the plan's own ndata -- which is the grouping
   knob, there being no second one.  Returns total crossings, or -1. */
int ap_mf_run_series(ap_mf_plan *p,
                     const float *series, size_t nseries,
                     const size_t *start, const size_t *win_start,
                     const size_t *win_end, int nblocks,
                     int t0, int nt, size_t binsize, float threshold,
                     ap_peak *peaks, int *counts);

/* Interpolated coarse maximum, alongside the peak scan.  hlo/hhi are complex
   taps (2*ntap floats each) for the two half-sample offsets, ncand is how many
   of the largest grid samples to probe, and out receives one value per pair in
   the same [nd][nt] order as ap_mf_run's peaks.  Pass a NULL tap pointer to
   turn it off.  See docs/hierarchical.md for why this brackets the second
   coarse transform rather than replacing it. */
/* ap_mf_set_interp and ap_mf_interp_pause are gone. Interpolation was
   removed with the U / oversample design; the plan state and the innermost
   loop block that used them were unreachable -- interpolation was never
   exposed to Python -- so the whole path went with them. */

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
 * The caller supplies band and a nonnegative coarse threshold. The native
 * engine does not read files or derive calibration; Python resolves measured
 * files before execution. snr/fd/taps are retained for ABI compatibility.
 */
typedef struct ap_hmf_plan ap_hmf_plan;

ap_hmf_plan *ap_hmf_create_ex(size_t n, int ndata, int ntmpl, float snr, float fd,
                              size_t band, int taps);
void         ap_hmf_destroy(ap_hmf_plan *p);

size_t ap_hmf_nbins(const ap_hmf_plan *p, size_t binsize, size_t start, size_t end);
/* Reference SNR distribution: expected power per bin of the filter OUTPUT,
 * length n, real, any scale.  Setting it is usually the right thing to do.
 *
 * By default each template's band fraction is computed
 * from the template itself, which assumes its own power distribution is the
 * distribution of the SNR it produces.  That holds only when the data is white
 * and the template is whitened.  It fails, for instance, when the template is a
 * broadband ratio filter whose output reconstructs a strongly low-frequency
 * signal: the coarse threshold would read the filter and be badly wrong.
 *
 * In practice the output distribution is a property of the SIGNAL, not of the
 * individual template, and is near-identical across a bank -- so supply it once
 * here rather than tuning per template.  Doing so also skips the per-template
 * measurement at ingest entirely.
 *
 * Pass NULL to use each template. Existing templates are rescaled on change. */
int    ap_hmf_set_reference(ap_hmf_plan *p, const float *power);
/* Legacy ABI: invalidate the gate; the caller must supply a recalibrated
   threshold before the next execution. No model or clamping is applied. */
int    ap_hmf_set_first_stage(ap_hmf_plan *p, float snr);
/* Supply a finite nonnegative coarse threshold in coarse-output units.
   A negative value marks the plan unconfigured; execution then fails. */
int    ap_hmf_set_threshold(ap_hmf_plan *p, float t);

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

/* Read the supplied scalar coarse threshold. Returns -1 if unconfigured.
   The threshold argument is retained for ABI compatibility and is ignored. */
int ap_hmf_coarse_thresholds(ap_hmf_plan *p, float threshold, float *thr);

/* The supplied band and taps, for reporting. */
void ap_hmf_config(const ap_hmf_plan *p, size_t *band, int *taps);

int ap_supported(size_t n);

/* Which back end the CPU selected: "avx512", "avx2", or "unsupported". */
const char *ap_isa(void);

#ifdef __cplusplus
}
#endif
#endif
