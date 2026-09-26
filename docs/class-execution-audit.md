# Class layout and series scheduling audit — 2026-09-26

Status: the approved changes are implemented. See the
[implementation and timing report](class-execution-changes.md) for results.
The measurements below describe the original audit baseline.


`run_series()` is the right execution boundary: one call should cover many
blocks and the largest useful template bank. It already avoids a host FFT
round trip and keeps GPU spectra resident between forward and correlation.
There are worthwhile scheduling, validation and cache improvements outside
the kernels. The most useful simplification is one internal series-layout
planner, with backend-specific execution and storage.

This is an audit with measured prototypes, not a production runtime patch.
Kernel work in the shared checkout was left untouched.

## Scope and reproducibility

Python classes and shipped GPU shaders were isolated at `87cff6f`; the local
Python 3.13 native extension was copied into that snapshot. Its exact binary
hash and the shader manifest hash are recorded in the
[measurements](audits/class-execution-2026-09-26/measurements.json).
Measurements used Ryzen AI MAX+ 395 / Radeon 8060S, AVX3 and Vulkan.
Metal was inspected, not timed. Concurrent development affects absolute
latency; use within-experiment comparisons, not ratios between separate runs.

The reproducible driver is `tools/audit_class_execution.py`. For example:

```bash
PYTHONPATH=/path/to/snapshot/python python tools/audit_class_execution.py \
  --suite reorder_cpu --device cpu --rounds 7 --json reorder.json
```

Available suites: `batching`, `layout`, `cache`, `cache_limits`, `caller_chunks`,
`vector_validation`, `reorder_cpu`. GPU suites need a working Vulkan device;
this machine's conda Python also needs
`LD_PRELOAD=/usr/lib64/libstdc++.so.6`.

Timings cover warm public calls, including forward transforms, grouping,
filtering and output assembly. Variants within a timing group alternate order;
raw samples and ranges are saved. Prepared-layout and shared-source probes in
`layout` run separately and are exploratory, not paired speedup evidence.
Hierarchical experiments explicitly use band 256 and coarse threshold 4;
these isolate execution and do not measure calibration safety or FDR. CPU and
GPU coarse arithmetic can produce different survivor populations, so these
results do not establish cross-device hierarchical speedups.

Changed batching, CPU reordering and vector-validation prototypes compare
returned indices exactly and values within float32 tolerance. Full edge-case
and device tests are still required before adopting the prototypes.

## 1. Batch policy is inconsistent and its documentation is wrong

There are three independent controls:

| Path | Actual block grouping |
|---|---|
| Flat CPU | Adjacent equal-window blocks, up to `ndata` |
| Hierarchical CPU | Adjacent equal-window blocks, up to internal `dgroup` (default 8, reduced to bound held spectra to 4 MiB); `MF_DGROUP` is diagnostic |
| GPU, either class | All equal-window blocks, with a 64 MiB working-budget limit and a 65,535-row dispatch cap; independent of `ndata` |

The `run_series()` docstring says `ndata` is the single grouping knob. That
only describes the flat CPU implementation. A hierarchical CPU plan can
allocate capacity for a large `ndata` while still processing eight series
blocks at a time. GPU construction allocates `_gdata` for `ndata`, although
series execution uses a separate shared workspace.

Flat CPU measurements, 128 blocks × 512 templates, one common window:

| Length | `ndata=1` | `ndata=8` | `ndata=32` |
|---:|---:|---:|---:|
| 1024 | 43.47 ms | 33.24 ms | 28.71 ms |
| 4096 | 179.44 ms | 173.70 ms | 169.42 ms |
| 16384 | 1026.20 ms | 768.21 ms | 780.12 ms |

At small lengths, grouping also enables the existing adaptive pair-packed
layout: it requires at least eight data rows and sixteen suitably aligned
contiguous templates, sufficient SIMD occupancy and a broad single bin.
Calling one block at a time prevents that dispatch decision even with a large
bank. At longer lengths grouping improves reuse in the existing 8×8 pair loop.

Do not increase every group size. Hierarchical CPU at length 16384 took
45.20 ms with `ndata=32`, default group 8, versus 48.85 ms with group 32.
Larger groups retain more spectra and can lose locality. Changing GPU `ndata`
did not change its series dispatch shape; small timing differences between
those plans are not evidence of a batching benefit.

**Recommendation:** separate stored-spectrum capacity from internal series
batch selection. Keep backend-specific, memory-bounded defaults. Correct the
docstring, allocate unused spectral-bank storage lazily, and expose selected
batch sizes for diagnostics before adding more public tuning knobs.

## 2. Share a layout planner; preserve fast backend execution

`MatchedFilter._series_layout` converts/validates arrays, then calls Python
`nbins()` once per block. GPU code rebuilds a set of window pairs and scans
all blocks for each distinct pair. CPU code independently discovers only
adjacent runs of equal windows. The extension correctly validates raw buffers
again at its independently callable boundary; that safety check should remain.

An array-based replacement for the Python window loop, retaining the other
public checks, measured:

| Workload | Existing | Vector validation prototype |
|---|---:|---:|
| CPU: 4096 blocks × 1 template, n=64 | 3.135 ms | 2.184 ms |
| GPU: same workload | 1.361 ms | 0.459 ms |
| GPU: 128 × 32, n=1024 | 0.245 ms | 0.222 ms |
| GPU: 128 × 512, n=4096 | 6.124 ms | 6.188 ms |

The large case is unchanged within measurement spread. This is a small-workload
optimization, not a promised general GPU multiplier. The prototype still needs
coverage for clipping, invalid ranges, large binsizes and DLPack inputs.

CPU grouping can also reuse the GPU's global equal-window policy. With two
alternating windows, n=1024, 128 × 512, grouping layout arrays and restoring
output order measured:

| Path | Adjacent-only grouping | Group + filter + restore order |
|---|---:|---:|
| Flat CPU | 53.50 ms | 29.73 ms |
| Hierarchical CPU | 13.18 ms | 7.74 ms |

Sorting and output reordering are included. Random input peaks agreed.
This is particularly useful for interleaved windows; ordinary overlap-save
interiors already form long equal-window runs.

**Recommendation:** an internal layout record containing normalized windows,
bin count, groups and optional output permutation. Fast-path a uniform window
and already contiguous groups. Use slices for contiguous groups rather than
advanced indexing. Keep the full native series loop and its single Python/C
boundary; do not replace it with per-block Python calls. An immutable public
prepared-layout object is optional later, not required for these gains.

## 3. Vulkan recordings should not own duplicate banks

Vulkan's dispatch key includes window and threshold because those constants
are recorded into its command buffer. Each recording also owns another copy
of the data/template buffers unless the inputs use shared allocations.
Metal already separates allocation identity from those changing constants:
its buffer key is shape-based and it encodes constants each call. Do not force
both backends into Vulkan's current cache structure for source uniformity.

At n=4096, 128 × 512 with two windows, an ordinary bank caused two template
writes totalling 32 MiB on the first call; warm repeated calls needed no
writes. A shared template bank required no backend template writes. These
counters exclude the separate NumPy source-series copy, which still occurs
for an ordinary source array.

Forty changing thresholds across two windows took about 528 ms with an
ordinary bank and 248 ms with a shared bank. This comparison was run in
separate measurement groups, but its copy mechanism is also directly visible
in the code: new recordings create and populate new template buffers.
Changing thresholds must still change results; simply dropping constants
from the Vulkan recording key is incorrect.

**Recommendation:** keep bank allocations/version tracking separate from
command recordings. Reuse shape-compatible output/work buffers. Retain
recorded commands where they pay, with a distinct small recording cache.
This reduces both duplicate storage and residency bookkeeping. Preserve
input-generation invalidation, subrange identity, ownership and deferred
forward lifetime guarantees.

## 4. Cache accounting and eviction amplify unusual window layouts

The common cache policy sums every buffer reference, including repeated
borrowed references to the same allocation. In a 128-window case, allowing
all recordings to remain resident produced 169,398,784 counted bytes for
35,181,056 distinct allocation bytes. The accounting overstates ownership by
about 4.8× and can evict useful commands prematurely.

The default 32-entry cap then clears the whole cache. A working set larger
than that cap can repeatedly rebuild every recording. At n=1024, 128 × 32,
128 different windows, raising the entry cap to 256 reduced the measured
median from 32.66 ms to 9.85 ms. A prior comparison gave 27.51 → 8.21 ms;
absolute timing moved with load, but both comparisons were about 3.3×.
The retained-cache comparison still makes 128 synchronous submissions: it
isolates cache churn, not the whole window-fragmentation cost.

**Recommendation:** account once per owned allocation, separate memory and
recording budgets, and evict selectively instead of clearing everything.
Keep a hard bound; simply raising the default entry cap is a diagnostic,
not a complete memory-management fix. A cache miss between deferred forward
and correlation must still safely complete or preserve the forward command.

## 5. Avoid repeating series preparation at the caller boundary

At n=4096, 128 blocks × 512 templates on GPU:

| Caller pattern | Time |
|---|---:|
| One `run_series()` call | 6.60 ms |
| Eight calls with 64-template subranges | 8.34 ms |
| 128 calls, one block each | 31.91 ms |

Each template-subrange call repeats the source preparation and forward FFTs.
Nonzero-offset shared bank slices also fall back to copies because
`shared_buffer()` recognizes only contiguous allocation prefixes. The chunked
measurements include list construction but exclude concatenation; the
results were concatenated and checked separately for correctness.

**Recommendation:** prefer one call per source segment and full useful bank.
When template chunking is necessary, prepare a data chunk once and run all
its template chunks before advancing. Bank offsets/versioned resident buffers
can avoid the nonzero-offset copy. This can be an internal scheduler change;
an explicit prepared-spectra API is justified only for callers that actually
reuse data across separate searches. Avoid adding an overlapping second
filter abstraction before that use case is established.

## 6. Output handling has avoidable copies and duplicated policy

CPU `run` and `run_series` write native `ap_peak` storage, then the extension
copies to index/value arrays, then Python packs a structured array unless
`raw=True`. GPU reads separate buffers into new NumPy arrays; series execution
scatters those into full result arrays and then packs another structured
array. The series result arrays are initialized even though every valid
output row is subsequently overwritten.

Hierarchical GPU `run(raw=True)` still allocates and fills a structured array,
then returns its fields. Flat GPU raw execution returns separate arrays
without that assembly. The raw interfaces therefore have different strides
and different allocation costs despite matching values and dtypes.

**Recommendation:** one result-formatting helper and one execution-result
contract. Make hierarchical raw avoid structured packing too; reuse output
capacity and bypass aggregate scatter for a single complete contiguous group.
A `read_into` backend method could remove an additional readback copy.
Returning views into mapped GPU storage needs an explicit lifetime contract
and should not be smuggled in as this cleanup. Small one-bin timing differences
for raw versus structured were not reliably significant here; prioritize
validation and cache work first, then measure many-bin cases.

## 7. Safe simplifications and changes to avoid

Low-risk cleanup candidates:

- Share common class state initialization. The two constructors duplicate
  readiness, held arrays, output buffers, GPU counters and dirty flags.
- Centralize range validation and result formatting now repeated in CPU,
  flat GPU and hierarchical GPU `run` methods. Keep one backend execution hook.
- Move hierarchical-specific preparation into its subclass. Keep a common
  series scheduler instead of adding more device branches to public methods.
- Reconcile stale comments: hierarchical GPU execution already uses device
  compaction and indirect refinement, not host survivor round trips.
- Split reusable GPU source storage from workspace capacity. The current
  workspace key includes source length, so changing only a segment's length
  replaces spectra and start buffers too. Consider grow-only capacities with
  explicit trimming rather than exact-size caching everywhere.
- Bulk native setters would remove Python row loops when banks change often.
  These are ingest costs, not steady-state wins for an unchanged template bank.
- Release obsolete held CPU data references after successful complete-bank
  replacement. The current dictionary can retain previous per-row arrays.
  Preserve references needed by lazy hierarchical refinement.

Do not merge every physical layout. CPU split/group-major and pair-packed
banks serve different SIMD access patterns; GPU kernels consume interleaved
or packed coarse data. Keep transformations at ingest, outside pair loops.
Also preserve lazy CPU full-data ingestion for hierarchical survivors.

Bank shape is part of dispatch eligibility, not just pair count. Small CPU
pair packing needs aligned template starts and enough template lanes. GPU
coarse tiling checks template divisibility and pairs-per-group divisibility;
odd subranges correctly take fallbacks. Padding or bulk-plus-tail dispatch
might help, but can also add allocations, fake refinements or launches.
That needs its own end-to-end comparison; it is not a safe automatic cleanup.

Keep separate forward and correlation GPU dispatches in one submission where
possible. They already share a completion wait. Fusing them blindly into each
pair kernel could recompute a data FFT for every template. Asynchronous
multi-buffer execution could overlap upload and compute, but adds ownership
and synchronization complexity; pursue it after the simpler changes above.

## Recommended order

1. Common vectorized layout validation and uniform-window fast path.
2. Global CPU window grouping with output-order restoration when beneficial.
3. Separate Vulkan bank residency from recordings; correct allocation accounting
   and bounded eviction.
4. Unify result formatting and class initialization; remove raw packing overhead.
5. Measure streaming bank updates, many-bin outputs and template-chunk reuse
   before considering new public APIs or asynchronous execution.

For each runtime change, retain unchanged kernels, alternate old/new timings
at small and large shapes, and cover both devices/classes, ragged and
interleaved windows, subranges, raw results, input mutation and cache eviction.
A faster isolated case is not sufficient evidence of no regression.
