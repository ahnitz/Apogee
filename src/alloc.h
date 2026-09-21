/* 64-byte aligned allocation that is safe on every libc.
 *
 * C11 requires aligned_alloc's size to be a multiple of its alignment.  glibc
 * ignores that and returns memory anyway; macOS enforces it and returns NULL.
 * Every call site here happens to pass a multiple today, but "happens to" is
 * not something to rely on when the failure mode is a null plan on one
 * platform only, so round the size up rather than audit each caller.
 */
#ifndef AP_ALLOC_H
#define AP_ALLOC_H
#include <stdlib.h>

#define AP_ALIGN 64

static inline void *ap_alloc64_raw(size_t bytes) {
  if (!bytes) bytes = AP_ALIGN;
  size_t r = bytes % AP_ALIGN;
  if (r) bytes += AP_ALIGN - r;
#if defined(__cplusplus) || defined(_ISOC11_SOURCE) \
    || (defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L)
  return aligned_alloc(AP_ALIGN, bytes);
#else
  void *p = NULL;
  if (posix_memalign(&p, AP_ALIGN, bytes) != 0) return NULL;
  return p;
#endif
}

#ifdef __cplusplus
/* C++ has no implicit void* conversion, and the kernels assign the result to
   a dozen different pointer types.  Returning a proxy that converts on demand
   keeps every call site identical between the C and C++ builds, rather than
   sprinkling casts that only one of the two needs. */
struct ap_alloc_proxy {
  void *p;
  template <typename T> operator T *() const { return static_cast<T *>(p); }
};
static inline ap_alloc_proxy ap_alloc64(size_t bytes) {
  return ap_alloc_proxy{ap_alloc64_raw(bytes)};
}
#else
#define ap_alloc64(bytes) ap_alloc64_raw(bytes)
#endif
#endif
