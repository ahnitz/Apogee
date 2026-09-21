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

static inline void *ap_alloc64(size_t bytes) {
  if (!bytes) bytes = AP_ALIGN;
  size_t r = bytes % AP_ALIGN;
  if (r) bytes += AP_ALIGN - r;
#if defined(_ISOC11_SOURCE) || (defined(__STDC_VERSION__) && __STDC_VERSION__ >= 201112L)
  return aligned_alloc(AP_ALIGN, bytes);
#else
  void *p = NULL;
  if (posix_memalign(&p, AP_ALIGN, bytes) != 0) return NULL;
  return p;
#endif
}
#endif
