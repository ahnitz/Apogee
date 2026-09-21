/* The kernel translation unit.
 *
 * foreach_target.h re-includes this file once per SIMD target Highway can
 * generate for the machine being built for; balanced-inl.h supplies the body
 * each time, specialised to that target's vector width.  HWY_DYNAMIC_DISPATCH
 * then picks one at run time from what the CPU actually reports.
 *
 * That replaces the hand-written __builtin_cpu_supports ladder and the
 * per-ISA compilation groups in setup.py: the set of kernels a build contains
 * is now whatever Highway decided it could compile, and the build file names
 * none of them.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "alloc.h"
#include "matchedfilter.h"
#include "backend.h"

#undef HWY_TARGET_INCLUDE
#define HWY_TARGET_INCLUDE "kernel.cc"
#include "hwy/foreach_target.h"      // must come before highway.h

#include "balanced-inl.h"

#if HWY_ONCE
#include "hwy/targets.h"

namespace ap {
HWY_EXPORT(Backend);

/* MF_ISA names a Highway target -- SSE4, AVX2, AVX3, NEON, EMU128 -- and
   narrows the runtime choice to it.  Highway already owns both the list of
   targets in this build and the CPU detection, so forcing one is a matter of
   telling it what to consider rather than of keeping a parallel table.
   Anything unrecognised is an error and leaves the library unusable, so a
   typo in a benchmark script cannot quietly measure the default. */
static bool isa_failed = false;

static void apply_env(void) {
  const char *e = getenv("MF_ISA");
  if (!e || !*e) return;
  for (int64_t t : hwy::SupportedAndGeneratedTargets()) {
    if (!strcasecmp(e, hwy::TargetName(t))) {
      hwy::SetSupportedTargetsForTest(t);
      return;
    }
  }
  fprintf(stderr, "matchedfilter: MF_ISA=\"%s\" is not one of:", e);
  for (int64_t t : hwy::SupportedAndGeneratedTargets())
    fprintf(stderr, " %s", hwy::TargetName(t));
  fprintf(stderr, "\n");
  isa_failed = true;
}

}  // namespace ap

/* The targets this build contains that this CPU can also run, widest first.
   Highway owns both halves of that question, so the list is asked for rather
   than kept. */
extern "C" int ap_target_count(void) {
  return (int)hwy::SupportedAndGeneratedTargets().size();
}

extern "C" const char *ap_target_name(int i) {
  const auto ts = hwy::SupportedAndGeneratedTargets();
  if (i < 0 || (size_t)i >= ts.size()) return NULL;
  return hwy::TargetName(ts[(size_t)i]);
}

/* Narrow the runtime choice to one target, by name, or restore the default
   when name is NULL.  Existing plans keep the kernel they were built with:
   they hold the back end, not a promise to re-dispatch. */
extern "C" int ap_set_target(const char *name) {
  ap::isa_failed = false;
  /* Restore first: while a target is forced, SupportedAndGeneratedTargets
     reports only that one, so searching without this can only ever find the
     target already selected. */
  hwy::SetSupportedTargetsForTest(0);
  if (!name) return 0;
  for (int64_t t : hwy::SupportedAndGeneratedTargets()) {
    if (!strcasecmp(name, hwy::TargetName(t))) {
      hwy::SetSupportedTargetsForTest(t);
      return 0;
    }
  }
  return -1;
}

extern "C" const ap_backend *ap_backend_active(void) {
  static const bool once = (ap::apply_env(), true);
  (void)once;
  if (ap::isa_failed) return NULL;
  return HWY_DYNAMIC_DISPATCH(ap::Backend)();
}
#endif
