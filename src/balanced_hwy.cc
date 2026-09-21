/* The width-generic kernel, compiled against Google Highway.
 *
 * balanced.c is included rather than duplicated: it speaks only through the
 * V_* macros, so the same source serves the intrinsic, vector-extension and
 * Highway builds.  HWY_BEFORE_NAMESPACE applies the target attributes to
 * every function in the region, which is what Highway's always-inline ops
 * require of their callers.
 */
#include "hwy/highway.h"
HWY_BEFORE_NAMESPACE();
#include "balanced.c"
HWY_AFTER_NAMESPACE();
