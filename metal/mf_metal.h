/* matchedfilter on the Apple GPU: C interface.
 *
 * The same batched matched filter as ap_mf_* in matchedfilter.h -- D data
 * spectra against T template spectra, the loudest sample per bin of a lag
 * window -- executed by Metal kernels (metal/kernels.metal) instead of the CPU.
 * Inputs, output layout, threshold and window semantics are those of
 * ap_mf_run, so the two can be swapped and compared pair for pair.
 *
 * Lengths are the powers of two from 256 to 2^21.  Nothing here links the CPU
 * library; this file and mf_metal.m are the whole GPU back end.
 */
#ifndef MF_METAL_H
#define MF_METAL_H
#include <stddef.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct mfm_plan mfm_plan;

/* 1 if a Metal device is present and the kernels compiled. */
int         mfm_available(void);
/* Name of the GPU, or NULL; and the last error message, if any. */
const char *mfm_device_name(void);
const char *mfm_last_error(void);
int         mfm_supported(size_t n);

mfm_plan *mfm_create(size_t n, int ndata, int ntmpl);
void      mfm_destroy(mfm_plan *p);
size_t    mfm_nbins(const mfm_plan *p, size_t binsize, size_t start, size_t end);

/* Ingest: n interleaved complex float32, the unnormalised forward transform
   in natural order.  Copied into GPU-visible memory; the caller's array is
   not retained.  Returns 0, or -1. */
int mfm_set_data    (mfm_plan *p, int d, const float *spec);
int mfm_set_template(mfm_plan *p, int t, const float *spec);

/* Run the pairs [d0,d0+nd) x [t0,t0+nt).  Row (d-d0)*nt + (t-t0) of the
   outputs holds that pair's nbins peaks: lag (or -1), value (interleaved
   complex) and magnitude.  counts, if non-NULL, receives crossings per pair.
   Returns total crossings, or -1. */
int mfm_run(mfm_plan *p, int d0, int nd, int t0, int nt,
            size_t binsize, float threshold, size_t start, size_t end,
            long long *index, float *value, float *magnitude, int *counts);

/* GPU execution time of the last mfm_run, in seconds: the kernels alone,
   without the submission and the host-side copy of the peaks. */
double mfm_last_gpu_seconds(void);

/* The tile shape the plan chose, for reporting: 0 for the one-pass kernel
   (a and b are then the pairs per threadgroup and n), else the four-step
   split n = a*b and the column tile w. */
void mfm_config(const mfm_plan *p, int *fourstep, int *a, int *b, int *w);

#ifdef __cplusplus
}
#endif
#endif
