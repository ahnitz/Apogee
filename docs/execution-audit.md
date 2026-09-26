# Execution and dead-code audit — 2026-09-26

Audited the shared checkout at `782db3b` and independently reproduced the
execution bugs with the isolated committed `a89bafb` implementation/kernels.
Concurrent wide-radix development is present locally; the findings below do
not depend on it. This is an audit, not a runtime-fix patch.

The CI run for `a89bafb` passed every job, including Python 3.9–3.14, wheel,
benchmark, generated files and macOS Metal. Green CI does not cover the new
boundary/race reproducers below.

## Follow-up

The GPU tie race, Metal ownership, production-kernel build coverage and dead
code/documentation findings have been addressed; see
[cleanup validation](peak-race-cleanup.md). The CPU coarse-gate boundary
finding remains open. The greater-than-32-bit binsize finding was explicitly
deprioritized by the user. The original observations below are retained as
the audit record.

## P1: GPU ties can return an index and value from different samples

`src/gpu/tierb.slang`, the peak writeback in `filterOne`, lets every thread
whose magnitude equals the maximum write both `peakIdx` and `peakVal`.
There is no election of a unique writer. Allowing any tied index is fine;
allowing the value to come from a different tied index is not.

Reproducer: length 16384, 32 data rows, 32 templates, all with only frequency
4096 set to one. Every correlation sample has magnitude one, and its complex
value must be `[1, i, -1, -i][index % 4]`. Across 12 calls (12288 pairs), the
committed kernels returned **117 index/value mismatches** on the Radeon
8060S. The concurrent checkout produced 101. The count varies with scheduling.
Lengths 1024 and 4096 did not reproduce it in the same run; that is not a
proof of safety. The non-atomic multiple-writer source is shared by backends.

Fix direction: select one winner per bin before writing the index/value pair.
Preserve the efficient single-bin reduction and benchmark the extra election,
particularly for many-bin calls. Extend the existing tie tests to verify the
complex value at the returned index, not only its magnitude. A deterministic
first-index policy is optional; a consistent pair is mandatory.

## P1: CPU coarse gating can dismiss a valid hit even with threshold zero

`src/hmf.c` calls the coarse peak search with `minev = cal_thr`, then treats
`ce.index < 0` as dismissal. That peak search only returns a sample strictly
above its threshold. The later `bestmag >= thr` test cannot recover samples
already excluded by the coarse search.

Two deterministic cases at length 1024, band 256, one data row/template:

| Spectrum (both data/template) | Coarse threshold | CPU | GPU |
|---|---:|---|---|
| Only frequency 300 is one | 0 | No peak; 0 refinements | Magnitude 1; 1 refinement |
| Only frequency 0 is one | 1 | No peak; 0 refinements | Magnitude 1; 1 refinement |

The first loses a real signal even when the coarse gate is intended to admit
all pairs. The second exposes strict-versus-inclusive threshold semantics.
The final reporting threshold was zero in both cases.

Fix direction: make the coarse admission comparison explicit and identical
across CPU/GPU. Handle zero as an unconditional gate if retaining current GPU
semantics; avoid broadly disabling the coarse threshold optimization for
ordinary positive thresholds. Add both `run` and `run_series` boundary tests.

## P2: Large binsizes truncate in GPU push constants

The Python API accepts positive binsizes larger than the transform, correctly
meaning one bin. CPU uses a machine-size binsize; GPU packs it into uint32
without first capping or rejecting it. The separately computed shift can
also become 32 or larger.

Reproducer: length 1024 with a unique peak of magnitude 1024 at lag 37,
reporting threshold 500. Binsizes 1024, 4294967296 and 4294967297 all return
lag 37 on CPU. GPU returns lag 37 for 1024 but `(index=0, value=0)` for both
large sizes in the measured run. Those latter results are not valid
no-detection sentinels either. Exact uninitialized output is not guaranteed.

Fix direction: clamp the effective bin width to the searched window before
computing shifts and packing GPU parameters. This preserves the API and
avoids an unnecessary CPU/GPU restriction. Cover flat/hierarchical and series
paths, including `2**32` and `2**32+1`.

## P2: Metal owned objects are not released

Static ownership audit: `_mtlcompute.py` creates a command queue with
`newCommandQueue`, libraries with `newLibrary...`, functions with
`newFunctionWithName:`, pipeline states with `newComputePipelineState...`,
and fallback descriptors with `alloc/init`. The library/function/descriptor
references are not released after pipeline creation. `Context.destroy()`
clears the Python pipeline dictionary without releasing the owned Metal
pipeline states or command queue. Rebuilding a pipeline on the fallback
path also loses the first owned pipeline reference.

Fix direction: balance owned Objective-C references on success and failure,
release cached pipeline states and the queue during idempotent teardown, and
preserve shared-array ownership. Add a mocked retain/release accounting test
plus a repeated-create/destroy check on macOS. This is established by source
ownership paths; a macOS memory-growth measurement was not performed here.

## P2: Forward kernels are outside the main rebuild/manifest checks

`tools/build_spirv.py` rebuilds correlation kernels but does not invoke
`tools/build_forward.py`. The Metal CI build calls only the former. The
forward and pack artifacts are absent from the manifest inspected by
`tests/test_kernels_ship.py`.

Consequently, changing the shared FFT source and running the normal build can
leave committed forward kernels stale while rebuilding correlation kernels.
A CPU-only installation test does not check the forward files exist. This is
a build/coverage gap, not evidence that today's forward artifacts are wrong.

Fix direction: give all production entry points one build/manifest path and
check that every advertised GPU length has its forward artifact on both
backends. Include generated-source freshness checks or reproducible hashes.

## P3: Dead code and obsolete descriptions

- `src/hmf.c`: `nskip` is incremented but never read/exported; `last_thr` is
  assigned but never read. Remove these write-only fields.
- `_mtlcompute.py` still maps `gatedTierB` to a removed kernel. Neither the
  builder nor production dispatch uses that entry.
- Both GPU hierarchical dispatch docstrings still describe coarse-even,
  coarse-odd and gated refinement, although the production pipeline is
  coarse, compaction and listed refinement. Nearby Python comments still
  mention three thresholds and recovery factors.
- `src/hmf_table.h` is no longer included by the native execution sources,
  yet CI still regenerates/checks it. Descriptions claiming runtime use of
  that compiled model contradict the explicit file-or-user calibration rule.
- `src/gpu/hierarchical.slang` and `hierarchical_fused.slang` have no production
  builder/runtime/test references; historical notes reference them. Archive
  them clearly as prototypes rather than treating them as production paths.

`taps`/the old oversampling argument are documented compatibility metadata;
that is different from accidental dead execution code. Removing their public
API or ABI positions needs an explicit compatibility decision.

## Reproduction

`python tools/audit_execution_contracts.py` emits JSON for the three execution
findings. It requires a usable GPU for the GPU comparisons, and deliberately
lives outside the passing regression suite until fixes can assert the intended
contract. On this Linux development machine the Vulkan runtime additionally
needs `LD_PRELOAD=/usr/lib64/libstdc++.so.6` with the conda Python.

Priority: fix the two P1 correctness bugs, clamp GPU binsizes, then address
Metal ownership and build coverage. Measure peak-search overhead when fixing
the tie race; dead-field/doc cleanup should not affect kernel performance.
