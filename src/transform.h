#ifndef AP_TRANSFORM_H
#define AP_TRANSFORM_H
/* Internal transform API.
 *
 * matchedfilter's interface is the matched filter; this is the machinery under it.  It
 * is a separate header rather than part of matchedfilter.h because a caller has no
 * reason to hold a transform plan - the MatchedFilter is the plan - and every
 * symbol here is used only by src/matchfilt.c, the tests and the benchmarks. */
#include <stddef.h>
#include "matchedfilter.h"

typedef struct ap_plan ap_plan;

ap_plan *ap_create(size_t N);
void     ap_destroy(ap_plan *p);
const char *ap_plan_backend(const ap_plan *p);
int      ap_lane_width(void);

/* The SIMD targets this build holds that this CPU can run, widest first, and
   a way to narrow the choice to one of them for a comparison.  NULL restores
   the default. */
int         ap_target_count(void);
const char *ap_target_name(int i);
int         ap_set_target(const char *name);

/* The plan's actual N1 x N2 split.  The matched filter stores spectra in the
   layout stage A walks, which depends on this - recomputing it independently
   would silently diverge the moment the split heuristic changed.  Returns 0 if
   the plan has no such split (the specialised 1024 kernel). */
int      ap_plan_split(const ap_plan *p, int *n1, int *n2);

/* Full transform, AP_FORWARD or AP_BACKWARD.  Neither direction scales by 1/N. */
void ap_fft(ap_plan *p, const float *in, float *out, int sign);

size_t ap_nbins(const ap_plan *p, size_t binsize, size_t start, size_t end);

/* Binned maximum over one transform, and the two variants the matched filter
   uses: split input (consumed in place, input not conjugated), and the fused
   product form that builds conj(D*T) inside the transform's load. */
int ap_binmax(ap_plan *p, const float *in, size_t dist, int B,
              size_t binsize, float threshold, ap_peak *peaks, int *counts,
              int sign, size_t start, size_t end);
int ap_binmax_split(ap_plan *p, const float *re, const float *im,
                    size_t binsize, float threshold, ap_peak *peaks, int *count,
                    int sign, size_t start, size_t end);
/* Does this plan have a fused product path?  The matched filter needs to know
   before ingest, because group-major storage is only correct if the fused
   loader will consume it. */
int ap_has_fused_prod(const ap_plan *p);

/* Ask the back end to keep the output series in a plan-owned buffer, so a
   caller can examine lags the peak scan discards.  NULL if unsupported. */
float *ap_series_buf(ap_plan *p, int on);
size_t ap_series_stride(ap_plan *p);
float ap_interp_max(ap_plan *p, size_t ws, size_t we, float evmax,
                    const float *hlo, const float *hhi, int K, int ncand,
                    float frac);

int ap_binmax_prod(ap_plan *p, const float *dr, const float *di,
                   const float *tr, const float *ti,
                   size_t binsize, float threshold, ap_peak *peaks, int *count,
                   int sign, size_t start, size_t end);

#endif
