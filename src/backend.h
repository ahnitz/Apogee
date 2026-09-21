#ifndef AP_BACKEND_H
#define AP_BACKEND_H
#include <stddef.h>
#include "matchedfilter.h"
/* One implementation of the transform, selected at runtime by CPU support. */
typedef struct {
  const char *name;
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
} ap_backend;
extern const ap_backend ap_be_avx512;   /* specialised: 1024 kernel + tuned 2^17..2^20 */
extern const ap_backend ap_be_bal8;    /* width-generic balanced split, 8 lanes (AVX2)  */
extern const ap_backend ap_be_bal16;   /* same source at 16 lanes, for cross-checking  */
/* The same source compiled against compiler vector extensions.  Level 0 is
   baseline x86-64 (or whatever the target's default is) and is the fallback
   that must run anywhere; level 2 adds AVX2 and FMA.  Only level 0 exists off
   x86, where there is nothing to fall back from. */
#ifdef AP_WITH_HIGHWAY
/* Same width-generic kernel again, this time on Google Highway.  Built only
   when Highway is available; AP_HWY_W is the lane count its target uses. */
extern const ap_backend AP_HWY_BACKEND;
#endif
extern const ap_backend ap_be_port80;
#if defined(__x86_64__) || defined(__i386__)
extern const ap_backend ap_be_port81;   /* AVX: 256-bit float, no FMA  */
extern const ap_backend ap_be_port82;   /* AVX2 + FMA                  */
#endif
#endif
