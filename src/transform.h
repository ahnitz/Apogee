#ifndef AP_TRANSFORM_H
#define AP_TRANSFORM_H
/* Internal transform API.
 *
 * apogee's interface is the matched filter; this is the machinery under it.  It
 * is a separate header rather than part of apogee.h because a caller has no
 * reason to hold a transform plan - the MatchedFilter is the plan - and every
 * symbol here is used only by src/matchfilt.c, the tests and the benchmarks. */
#include <stddef.h>
#include "apogee.h"

typedef struct ap_plan ap_plan;

ap_plan *ap_create(size_t N);
void     ap_destroy(ap_plan *p);
const char *ap_plan_backend(const ap_plan *p);
int      ap_lane_width(void);

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
int ap_binmax_prod(ap_plan *p, const float *dr, const float *di,
                   const float *tr, const float *ti,
                   size_t binsize, float threshold, ap_peak *peaks, int *count,
                   int sign, size_t start, size_t end);

#endif
