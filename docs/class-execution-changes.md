# Class execution changes — September 26, 2026

The class-level audit is implemented without changing kernels. `run()` and
`run_series()` share result formatting and the GPU dispatch method; flat and
hierarchical filters share initialization, range validation and series
scheduling. Series execution adds block layout planning and forward FFTs.
The CPU series executors continue to use the regular filtering routines after
preparing each group. Their existing bounded hierarchical group size is kept.

## Changes

- Validate series windows with array operations, with a scalar path for one
  block. Clamp windows consistently and reject differing bin counts before
  native execution.
- Group repeated CPU windows across the whole segment, then restore output
  order. Already grouped windows avoid a permutation. CPU execution avoids
  building the GPU dispatch-group list.
- Reuse GPU FFT/start allocations when source length changes. Keep ordinary
  source upload capacity for shorter subsequent segments. A single uniform
  batch returns its output without an extra aggregate allocation and copy.
- Allocate GPU data/template banks when supplied, avoiding unused data-bank
  storage for series-only plans. Preserve shared-array ownership and setter
  invalidation. Release obsolete CPU per-row input references after a complete
  bank replacement.
- Separate Vulkan storage shapes from window/threshold command recordings.
  Equal shapes reuse input, intermediate and output buffers. Input freshness
  belongs to storage, so visiting another recording cannot restore stale
  spectra. Shared allocations count once toward the memory budget.
- Evict least recently used records instead of clearing the whole cache.
  Vulkan retains up to 32 storage shapes and 256 recordings; Metal retains
  32 shape entries. Both retain a 512 MiB allocation budget. Evicting the last
  storage user releases its buffers; evicting a pending forward recording
  submits it before freeing the command.
- Bound large GPU dispatches in both public entry points. At lengths 32768
  and 65536, a dispatch covers at most 2^29 point-pairs, also respecting the
  Vulkan device's X dispatch limit. The previous default 128×512, n=65536
  workload lost the device on this driver; bounded submissions complete even
  when every hierarchical pair refines. This controls worst-case submission
  work rather than relying on a low average survivor rate.
- Return hierarchical GPU raw arrays directly, without constructing a
  structured result first. Counts and structured results use the common
  formatter.

Physical CPU and GPU layouts remain backend-specific. Template-offset APIs,
asynchronous execution and new tuning controls were not needed for these
changes. The measurements below assess the remaining overhead before adding
such interfaces.

## Measurement method

Measurements use Ryzen AI MAX+ 395 / Radeon 8060S, AVX3 and Vulkan. Times are
warm, synchronous public calls, including validation, output formatting and
completion waits. `run()` starts with supplied spectra; `run_series()` also
uploads the time segment and performs its forward transforms. Kernel-only
latency is not reported here.

The comparison freezes package files from `600cd5c` and copies the same local
native binary and shaders into both packages. The candidate adds only this
class/cache patch. The concurrent CPU broadcast and calibration changes are
excluded, so these numbers do not claim their combined performance.

Hierarchical cases use an explicit band of 256 and coarse threshold 4, with
seeded Gaussian data and exponentially decaying template power. They measure
execution cost, not a false-dismissal guarantee. Results depend on the fraction
of pairs refined, the requested bins, and the number of distinct windows.

`tools/bench_class_changes.py` saves all samples and compares numerical output
before timing. It alternates baseline/candidate order. CPU controls can share
the same native plan to separate Python changes from native allocation/cache
placement. The JSON records the native binary hash and comparison method.

```bash
LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/bench_class_changes.py \
  --baseline /path/to/baseline/python/matchedfilter \
  --candidate /path/to/candidate/python/matchedfilter \
  --output comparison.json
```

The preload above is specific to the local Conda/Vulkan environment; it is not
a library requirement. Metal lifetime/accounting tests run here, but Metal
hardware performance remains unmeasured.

## Public-call timings

All values below are milliseconds for **128 blocks × 512 templates**, searching
the central half of each block and returning one peak per pair. Seven rounds
were used through n=16384; the large GPU run used three. The large CPU rows
come from the preceding separate-plan comparison; no CPU execution code
changed between those measurements and the dispatch-bound fix.

| Filter | n | CPU `run()` | CPU `run_series()` | GPU `run()` | GPU `run_series()` | GPU series speedup |
|---|---:|---:|---:|---:|---:|---:|
| flat | 1024 | 31.051 | 31.456 | 1.246 | 1.269 | 24.8× |
| flat | 4096 | 191.468 | 192.938 | 5.735 | 5.978 | 32.3× |
| flat | 16384 | 781.754 | 783.365 | 49.428 | 50.852 | 15.4× |
| flat | 65536 | 3902.806 | 3886.367 | 3144.160 | 3090.206 | 1.3× |
| hier | 1024 | 7.136 | 7.334 | 0.375 | 0.433 | 16.9× |
| hier | 4096 | 13.506 | 14.124 | 0.682 | 0.808 | 17.5× |
| hier | 16384 | 54.524 | 59.093 | 4.076 | 4.650 | 12.7× |
| hier | 65536 | 218.861 | 246.207 | 356.597 | 359.296 | 0.7× |

CPU hierarchical refinement rates are about 3.5–4.8%; GPU rates are about
7.0–9.2% in these runs. The existing CPU coarse scan narrows to the requested
window (with a coarse-sample margin); the GPU coarse scan covers the whole
block. The GPU therefore admits more noise pairs for this half-window
workload. These are timings of the actual current paths, not equal-work
coarse-kernel throughput comparisons. Narrowing the GPU coarse scan is a
remaining kernel-side opportunity and is outside this class patch.

A universal 50× GPU speedup is not achieved. The bulk n=1024–16384 cases show
substantial gains, but n=65536 is a clear performance gap. Its similar `run()`
and `run_series()` times rule out series preparation as the dominant cost.
The dispatch bound repairs reliability; it does not repair the large-transform
kernel's throughput. The concurrent kernel work should be remeasured on the
same shapes before publishing combined results.

The large stress reproduction also admitted every hierarchical pair. Both
entry points completed and returned the expected results after splitting;
the unsplit baseline lost the Vulkan device. No successful baseline GPU timing
is claimed for that failing case.

## Development priority

Keep every supported GPU length. Focus throughput work on **n=2048–8192**;
retain 32768 and 65536 as supported paths without making their optimization
the immediate target. Compare both large and small batches before changing a
dispatch rule. In the [earlier size sweep](measurements/device-paths-all-sizes-2026-09-26.json),
flat GPU filtering remained 24–40× faster than CPU across 2048–8192 at
128×512. Hierarchical GPU filtering used a smaller coarse band than CPU at
4096 and 8192 and refined far more pairs, so band selection and its measured
costs deserve attention in this range. The calibration and gate model have
since changed; those earlier rates are evidence for where to remeasure, not
current configuration recommendations. At 16×64, the
[fixed-shape sweep](measurements/device-paths-fixed-2026-09-26.json) also
found hierarchical GPU slower than CPU at 2048 and 4096. Keep correctness and
false-dismissal checks paired with any band or batch-policy change.

## Effect of the class changes

| Workload (`run_series`) | Before, ms | After, ms | Improvement |
|---|---:|---:|---:|
| CPU flat, n=64, 4096×1, 1 window(s) | 3.049 | 2.061 | 1.48× |
| GPU flat, n=64, 4096×1, 1 window(s) | 1.366 | 0.199 | 6.86× |
| CPU flat, n=1024, 128×512, 2 window(s) | 54.279 | 34.439 | 1.58× |
| CPU hier, n=1024, 128×512, 2 window(s) | 12.851 | 7.600 | 1.69× |
| GPU flat, n=1024, 128×32, 128 window(s) | 28.865 | 9.048 | 3.19× |
| GPU hier, n=1024, 128×32, 128 window(s) | 79.382 | 10.595 | 7.49× |
| GPU flat, n=1024, 16×16, 1 window(s), binsize=1 | 0.315 | 0.254 | 1.24× |
| GPU hier, n=1024, 16×16, 1 window(s), binsize=1 | 0.461 | 0.417 | 1.10× |

Large uniform cases remain close to baseline. An early approximately 3%
CPU many-bin slowdown led to the uniform-window fast path; the focused rerun
measured 0.625 versus 0.626 ms for flat and 0.230 versus 0.229 ms for
hierarchical calls. Tiny single-pair GPU calls remain much slower than CPU
because of launch/wait latency. A 21-round GPU check measured flat series calls
at 0.098 versus 0.096 ms and hierarchical calls at 0.102 versus 0.100 ms.
Shared formatting and caching do not remove that fixed GPU cost.

An early separate-plan measurement showed an apparent 12% CPU regression at
n=1024, 128×512. The [allocation control](audits/class-execution-changes-2026-09-26/cpu-allocation-control.json)
used the same native plan for both wrappers: uniform series calls measured
32.41 versus 32.28 ms; interleaved windows measured 53.36 versus 28.64 ms.
The main comparison now uses that control throughout. Native buffer placement
can change timings even when native code is byte-identical.

## Updates, chunks and output handling

- CPU flat, n=4096: one full-bank series call 192.938 ms; eight 64-template calls 181.940 ms.
- CPU hier, n=4096: one full-bank series call 14.124 ms; eight 64-template calls 17.618 ms.
- GPU flat, n=4096: one full-bank series call 5.978 ms; eight 64-template calls 7.912 ms.
- GPU hier, n=4096: one full-bank series call 0.808 ms; eight 64-template calls 6.242 ms.

Keep one large public call as the default. Small CPU flat chunk differences
need workload-specific measurement; GPU template splitting adds repeated
forward work and submissions. The library now performs the necessary large
GPU splits internally, preserving the template bank across data chunks.
No public template-offset or asynchronous interface was added.

- CPU flat, n=1024: replacing the 512-template bank before each series call costs 31.927 ms, versus 31.456 ms with an unchanged bank.
- CPU hier, n=1024: replacing the 512-template bank before each series call costs 8.255 ms, versus 7.334 ms with an unchanged bank.
- GPU flat, n=1024: replacing the 512-template bank before each series call costs 1.329 ms, versus 1.269 ms with an unchanged bank.
- GPU hier, n=1024: replacing the 512-template bank before each series call costs 2.891 ms, versus 0.433 ms with an unchanged bank.

The many-bin cases in the comparison return 512 bins for each of 16×16 pairs.
They include output transfer and formatting. Hierarchical raw output now
avoids structured packing and returns contiguous arrays.

## Validation and artifacts

The full isolated suite passed **878 tests**, with 10 skips and one expected
failure. The final uniform-window refinement passed **125 targeted tests**
with two skips. These runs used the Radeon 8060S; Metal hardware was unavailable.

Regression coverage includes interleaved packed CPU groups, flat/hierarchical
GPU results, raw/count output, source-capacity reuse and zero padding, shared
and ordinary input mutation, template subsets, selective eviction, storage
shape caps, unique allocation accounting, and bounded large dispatches.
GPU-free upload tests model shared storage while retaining production upload
and invalidation decisions.

Replacing a hierarchical GPU template bank remains relatively costly when
its normalization is recomputed from every template's full spectrum. Reducing
those temporary norm arrays is a possible follow-up; it must preserve the
scaling and coarse-gate behavior.

Artifacts:

- [Main comparison](audits/class-execution-changes-2026-09-26/comparison.json)
- [Large CPU calls](audits/class-execution-changes-2026-09-26/large-cpu.json)
- [Large GPU calls after the fix](audits/class-execution-changes-2026-09-26/large-gpu.json)
- [Uniform-window follow-up](audits/class-execution-changes-2026-09-26/uniform-fast-path.json)
- [Tiny GPU 21-round check](audits/class-execution-changes-2026-09-26/tiny-gpu.json)
- [CPU allocation control](audits/class-execution-changes-2026-09-26/cpu-allocation-control.json)

The large fixed GPU case can be reproduced without running the known failing
baseline using `--candidate-only --device gpu --case 65536,128,512,1,65536`.
