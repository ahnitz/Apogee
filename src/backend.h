#ifndef AP_BACKEND_H
#define AP_BACKEND_H
#include <stddef.h>
#include "matchedfilter.h"
/* One implementation of the transform, selected at runtime by CPU support. */
typedef struct {
  const char *name;
  int lanes;                 /* floats per vector, which the caller's layout needs */
  void *(*create)(size_t N);
  void  (*destroy)(void *);
  void  (*fft)(void *, const float *in, float *out, int conj);
  int   (*supported)(size_t N);
  /* binned maximum; writes exactly nbins dense entries */
  int   (*binmax)(void *, const float *in, size_t binsize, float thr,
                  ap_peak *out, int conj, size_t start, size_t end);
  /* Same, but the input is already split into re/im.  Two contract differences
     that exist to keep the matched filter's pair loop free of copies:
       - re/im are CONSUMED IN PLACE and left undefined on return;
       - the input is NOT conjugated for a backward transform.  The caller folds
         that into however it produced the data (for a product it is free), and
         conj here only sets the sign of the reported imaginary parts. */
  int   (*binmax_split)(void *, const float *re, const float *im, size_t binsize,
                        float thr, ap_peak *out, int conj, size_t start, size_t end);
  /* matched filter: form conj(D*T) inside stage A's load, so the product never
     reaches memory.  Inputs are read-only here, unlike binmax_split. */
  /* 1 if binmax_prod works for this plan's length */
  int   (*has_prod)(void *);
  /* report the plan's N1 x N2 split; 0 if it has none */
  int   (*split)(void *, int *n1, int *n2);
  int   (*binmax_prod)(void *, const float *dr, const float *di,
                       const float *tr, const float *ti, size_t binsize,
                       float thr, ap_peak *out, int conj, size_t start, size_t end);
  /* Keep the output series in a plan-owned buffer, laid out [k][re lanes][im
     lanes] as the scan writes it, so a caller can look at lags the peak scan
     discards.  NULL turns it off; returns the buffer. */
  float *(*series)(void *, int on);
  size_t (*series_stride)(void *);
  /* Interpolated maximum from the stored series: bounds the peak between grid
     samples without a second transform.  Compiled per target, so its scan
     vectorises. */
  float (*interp)(void *, size_t ws, size_t we, float evmax,
                  const float *hlo, const float *hhi, int K, int ncand,
                  float frac);
  /* Lane count when this plan batches PAIRS instead of frequencies -- the
     small-N path, where no balanced split exists.  0 for every other plan. */
  int   (*pairbatch)(void *);
  /* nlane pairs at once.  dr/di/tr/ti are [element][lane], AP_W lanes
     contiguous; `out` is dense [nlane][nbins]. */
  int   (*binmax_prod_batch)(void *, const float *dr, const float *di,
                             const float *tr, const float *ti, int nlane,
                             size_t binsize, float thr, ap_peak *out, int conj,
                             size_t start, size_t end);
  void *(*create_pairbatch)(size_t N);
} ap_backend;

/* The kernel for the target Highway's runtime dispatch selected, or NULL if
   MF_ISA named something this build does not contain. */
#ifdef __cplusplus
extern "C" {
#endif
const ap_backend *ap_backend_active(void);
#ifdef __cplusplus
}
#endif
#endif
