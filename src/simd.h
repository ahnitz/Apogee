/* SIMD surface for the width-generic kernel.
 *
 * One implementation now: Google Highway.  codelets.h and balanced.c speak
 * only through the V_* macros, and simd_hwy.h binds them to Highway ops that
 * lower to whatever the target has -- AVX2, AVX-512, NEON, SVE, RVV.
 *
 * The hand-written x86 intrinsics and the GCC/Clang vector-extension layer
 * that used to live here are gone.  Highway matched or beat the intrinsics on
 * AVX2, which is the target that matters, and beat the vector extensions
 * everywhere; keeping three layers to serve one of them was not worth the
 * three code paths.  See docs/highway.md for the measurements.
 */
#ifndef AP_SIMD_H
#define AP_SIMD_H
#include <stdint.h>

#ifndef AP_W
#error "define AP_W to the target's lane count"
#endif

/* `restrict` is C99 and not a C++ keyword.  The generated codelets use it
   heavily, so map it rather than generate different code per language. */
#ifdef __cplusplus
#define restrict __restrict
#endif

#if defined(__GNUC__) || defined(__clang__)
#define AP_ALWAYS_INLINE inline __attribute__((always_inline))
#else
#define AP_ALWAYS_INLINE inline
#endif

#include "simd_hwy.h"

#endif
