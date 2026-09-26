# CPU/GPU parity audit — 2026-09-26

The public filtering operations have parity over their shared supported sizes:
complex64 spectra, template/data subranges, arbitrary positive bin sizes,
clamped nonempty windows, thresholds, raw/structured results, per-pair counts,
overlap-save series, and explicit hierarchical coarse thresholds. CPU and GPU
are not interchangeable in every operating condition.

## Bugs corrected in this audit

* CPU reused-output shape when two successive subranges have the same number
  of pairs but different data/template dimensions.
* Negative setter indices, invalid bin sizes, empty dimensions, invalid pinned
  band/taps, malformed references, and invalid coarse thresholds now fail
  consistently before dispatch. Failed data ingestion does not enable run().
* Partially initialized banks are checked for the requested rows. In particular,
  CPU hierarchical refinement must never dereference an unset data pointer.
  Fully populated banks use constant-time readiness checks.
* `run_series` consumes internal data slots on CPU. A subsequent `run` now
  requires fresh `set_data` on both backends, preventing silent stale/staged
  input differences. Templates remain available.
* Resetting an explicit coarse threshold or changing the reference recalibrates
  the CPU plan. `set_first_stage` now affects measured threshold lookup as well
  as the fallback; explicit coarse thresholds retain precedence.
* GPU `stats`/`refine_rate` now count actual refinements using the existing
  indirect dispatch count, including refinements without a final detection.
  Both report lifetime totals. This reads one integer after the existing GPU
  completion wait; it introduces no submission or host-side gating.
* Public raw indices are int64 on both devices; values are complex64 and
  counts are int32.

Regression coverage lives in `tests/test_device_parity.py`, alongside the
existing cross-device numerical, caching, series, and bin/window matrices.
Vulkan ran on the Radeon 8060S. Metal dispatch/cache logic has host tests;
actual Metal execution still requires macOS CI.

## Supported differences and operational limits

| Area | CPU | GPU |
|---|---|---|
| Flat transform lengths | Powers of two 64–1048576 | 1024, 2048, 4096, 8192, 16384; device limits can reject 16384 |
| Hierarchical reference | Pinned plans can derive per-template statistics without a reference | Explicit common reference required for execution |
| Automatic configuration | CPU cost tables | Device cost tables, with documented fallback where absent |
| Coarse arithmetic | Float32 | Vulkan uses packed half precision for selected coarse bands; Metal uses its own kernels |
| Surviving peaks | Full filter arithmetic | Full float32 refinement; compare within roundoff, not bitwise |
| Series forward FFT | Native CPU FFT | NumPy host FFT plus GPU correlations |
| Series working memory | Internal block grouping | Materializes all block spectra; `ndata` is not a GPU memory cap |
| Result ownership | `run` and raw series may reuse storage | Allocation/readback details differ; copy results that must persist |
| Dispatch cache | CPU plan buffers; optional second pair-batch layout | Buffers/dispatches cached by shape and parameters; cache growth is not bounded by an eviction policy |

Further cautions:

* Independently tuned gates can dismiss different peaks. The guarantee tested
  here is that each reported survivor matches that device's flat result.
  An open gate must reproduce the complete flat result across devices.
* False-dismissal budgets are empirical calibration targets, not universal
  mathematical bounds. The existing pinned-band1024 capture workload misses
  three captured peaks; band2048 reproduces all twelve captures. See
  [cleanup notes](tooling-cleanup.md). CPU may use its fallback model where a
  pinned reference has no threshold-table coverage; GPU can refuse that case.
  Pin an explicit coarse threshold for a controlled execution comparison.
* `taps` is validated and part of configuration selection, but the measured
  raw coarse gate bypasses CPU interpolation and GPU kernels do not implement
  the CPU's uncalibrated interpolation fallback. Equal taps do not establish
  equality of every uncalibrated gate.
* Input arrays should be treated as immutable after ingestion until the next
  setter. CPU hierarchical plans retain data pointers while GPU plans upload
  copies. In-place caller mutation without another setter is not portable.
* Long series and sweeps over many distinct windows/thresholds can consume
  substantial GPU/host memory. Batch series at the caller and release old
  filter instances when dispatch-cache growth matters. Discrete-GPU transfer
  performance has not been established by this integrated-GPU audit.
* No complete 483-template PyCBC search or actual Metal run was performed in
  this session. Passing tests cannot establish the absence of every hidden bug.

## Performance check

Interleaved nine-round comparisons against the saved pre-coverage source
snapshots, using n=4096, 16 data rows and 64 templates: CPU flat/hierarchical
run and series medians stayed within 1%; GPU flat/hierarchical run stayed
within 2%. GPU flat series was 4.99→4.47 ms and hierarchical series
4.05→3.20 ms. GPU split-bin calls were 1.145→1.148 ms (0.3%). These are
representative checks, not a guarantee for every shape or discrete GPU.

The shared checkout also contained the pending chooser/tool migration from
margin-bearing configurations to `(band, taps)`. It is integrated with the
cleanup because the repaired tools depend on the extracted admission helper.
The concurrent cross-device matrix commit `0bb218d` was preserved.

Final validation after the shared matrix update: **595 passed, 5 skipped** in
50.15 seconds with CPU and Radeon 8060S Vulkan execution enabled. The skips
are platform/tool-specific, not failing parity assertions. `git diff --check`
also passes. The CPU pair-batch policy was separately exercised on AVX3,
AVX2 and SSE4. No actual Metal execution was available here.
