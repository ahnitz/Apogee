/* A monotonically increasing counter for the profiling paths.
 *
 * Only ever used for ratios between phases of one run (MF_HMF_PROF), so the
 * unit does not matter as long as it is consistent: cycles on x86, nanoseconds
 * elsewhere.  __rdtsc is x86-only, and reaching for it unconditionally is what
 * dragged <x86intrin.h> into a file that has no SIMD in it at all.
 */
#ifndef AP_TICKS_H
#define AP_TICKS_H
#include <time.h>
#if defined(__x86_64__) || defined(__i386__)
#include <x86intrin.h>
#endif

static inline unsigned long long ap_ticks(void) {
#if defined(__x86_64__) || defined(__i386__)
  return __rdtsc();
#else
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (unsigned long long)t.tv_sec * 1000000000ull + (unsigned long long)t.tv_nsec;
#endif
}
#endif
