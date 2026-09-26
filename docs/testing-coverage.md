# Coverage follow-up: state transitions and transfer costs

September 26, 2026. Builds on `gpu-cache-correctness.md`. Existing CPU
tuning work in the shared tree was preserved.

## Gaps covered

`tests/test_vk_upload_cache.py` now exercises the actual Vulkan and Metal
host dispatch methods with allocation/submission doubles. It checks input
contents and transfer counts, so it runs without GPU hardware. Numerical
Vulkan cases also execute on the Radeon 8060S.

- Revisiting cached dispatches after data or template changes, in both flat
  and hierarchical modes. Metal had the same stale-resident-input bug as
  Vulkan. Both now share residency bookkeeping.
- More than 2048 output bins, including a shorter final split. Vulkan was
  invalidating the inputs uploaded by earlier pieces of the same call;
  subsequent unchanged calls transferred them again unnecessarily.
- Updating data must leave full and coarse template buffers resident.
- Half packing preserves the shader's real-low/imaginary-high bit format
  for contiguous, strided, reversed and transposed inputs, including signed
  zero, half subnormals, overflow, infinities and NaNs.

`tests/test_series_lifecycle.py` covers both filter classes and both devices:

- Repeated series calls with forced reuse of the temporary spectrum's
  address. Hierarchical GPU filtering returned stale complex values because
  the dirty flag was not set for the new series. The test checks a known
  complex scaling, not only unchanged peak indices.
- Empty series and fully zero-padded blocks. The GPU attempted to gather
  from an empty array; it now supplies zero spectra, matching the CPU.
- Empty block lists, malformed array dimensions, negative/overflowing
  starts, invalid template ranges, and nonpositive binsizes. A 2-D series
  originally reached an oversized GPU buffer write and crashed Python.
  Validation is shared between the two classes and runs before native
  dispatch. Tests guard that boundary so a future regression reports a
  failure rather than killing the entire suite.
- Contiguous and interleaved window groups retain block order and agree
  with independent single-block calls, including complex values.
- Changing a hierarchical GPU reference recalibrates both the metadata and
  the executed gate. A deterministic signal crosses the gate under one
  reference and is rejected under the other. Previously the old band
  fraction and scaled templates survived the reference update.
- A new series does not re-upload an unchanged template bank. Flat GPU
  filtering previously forced this upload on every series call.

## Performance checks

Transfer counts are deterministic regression tests; wall-clock thresholds
are deliberately not embedded in the suite. Residency bookkeeping uses
array metadata, never spectrum hashes or content comparisons.

Interleaved before/after measurements used the same process and the same
inputs, nine rounds with alternating execution order, warm plans, and
numerical checks outside the timed loop. The baseline snapshots are from
the start of this follow-up (including the earlier Vulkan cache fix and the
existing CPU tuning edits). The diagnostic is `/tmp/mf_coverage_benchmark.py`;
its source snapshots are `/tmp/mf-api-before-coverage.py` and
`/tmp/mf-vulkan-before-coverage.py`.

The initial hierarchical-series comparison was about 6% slower. Profiling
showed the old repeated-series path performing **zero data uploads** because
of the stale-buffer bug. Correctness requires those uploads. To offset the
cost, contiguous window groups now use a slice instead of copying their
spectra; forward FFT scaling happens in place; already-complex64 FFT results
are not copied again; and little-endian half packing converts interleaved
components in one pass instead of constructing shifted integer temporaries.
The general-endian packing fallback is retained.

Final measured medians (milliseconds):

| Workload | Before | After |
| --- | ---: | ---: |
| CPU flat `run` | 2.599 | 2.638 |
| CPU flat `run_series` | 10.803 | 10.838 |
| CPU hierarchical `run` | 0.700 | 0.706 |
| CPU hierarchical `run_series` | 3.350 | 3.386 |
| GPU flat `run` | 0.217 | 0.220 |
| GPU flat `run_series` | 5.821 | 4.881 |
| GPU hierarchical `run` | 0.090 | 0.090 |
| GPU hierarchical `run_series` | 4.102 | 3.478 |
| GPU split-bin `run` | 0.444 | 0.445 |

Main workloads use n=4096, 16 data spectra × 64 templates for `run`, and
64 blocks × 64 templates for `run_series`. Hierarchical band=512 and a
fixed coarse threshold isolate execution from selection. Split-bin filtering
uses four data spectra, sixteen templates and binsize=1. These are local
measurements, not claims for every batch shape or device. The small CPU
differences varied in sign across repeated runs; no CPU kernel was changed.

## Validation limits

The final full suite passed **513 tests, with 5 skipped**, in 43.00 seconds.
That is 77 additional collected cases compared with the previous turn's
438 passed / 3 skipped. The two additional skips are CPU instances of a
GPU-only transfer contract. The focused host-only run, without device access,
passed 48 tests and skipped 38 GPU cases.

After the final optimizations, all twelve saved PyCBC captures were replayed
again through flat CPU and GPU `run_series`: all **842 detected peaks** agreed
in location and complex value at rtol=atol=1e-5.

Real GPU execution was tested on the Radeon 8060S with the system C++ runtime
preloaded so Mesa could load. Metal host logic was tested on Linux using
submission doubles; execution of Metal kernels and Apple performance still
require macOS CI. The full original PyCBC search and false-dismissal budget
study remain separate work; this follow-up does not claim to close them.

## Follow-up parity review

The subsequent CPU/GPU audit adds initialization/subrange validation,
shape-preserving output reuse, threshold reset/reference/first-stage state
transitions, raw dtype checks, and refinement counters that count work rather
than detections. See [the parity audit](cpu-gpu-parity.md) for remaining feature
and operational differences. Final shared-checkout validation: 595 passed,
5 skipped on CPU plus Radeon 8060S.
