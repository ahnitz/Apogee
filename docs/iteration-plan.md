# Iteration plan

A loop for making this package better, and the measurements that say whether
it worked. Run `python tools/health.py` before and after anything here.

This is a working document. When an item lands, replace its entry with the
number it moved and the commit, so the file records what actually changed
rather than what was hoped for.

## The loop

1. **Measure.** `python tools/health.py`, and the four-environment suite below.
2. **Pick one item** from the backlog with the largest measured gap. One.
3. **Write the failing check first.** If the check cannot fail, the item is
   not understood well enough to work on yet.
4. **Change it.**
5. **Re-measure on every environment**, not the convenient one. Most of the
   bugs in the backlog below were invisible on the development machine and
   obvious somewhere else.
6. **Record the number here**, and in the commit message.

### Principles

Added as they are earned, not in advance. Each one exists because its
absence cost something.

1. **Write the failing check first.** If the check cannot fail, the item is
   not understood well enough to work on yet.
2. **Compare the paths to each other, not each to a reference.** Every
   backend was checked against a numerical reference and never against the
   other through the same call, which is why `raw=True` returned three
   arrays on one path and two on the rest, undetected.
3. **Test the case where the right answer is nothing.** A filter's most
   important output is often silence: the dismissal, the empty bin, the
   refusal. `test_run_series_agrees_with_the_cpu` compares the two devices
   on data containing injections, so both sides fire and the comparison is
   made where firing is expected -- which cannot see a gate that fires when
   it should stay quiet. That is exactly the bug in item 0, sitting in a
   well-tested method the whole time. Every agreement test needs a companion
   whose expected result is an empty one.
4. **A probe that reproduces once has not reproduced.** Item 0 appeared,
   vanished under two variations, and returned only when the case was
   swept rather than sampled. Vary one thing at a time and sweep the
   parameter before believing either the presence or the absence of a
   fault.

### The four environments, because three of them found bugs the others could not

| environment | how | what it has caught |
|---|---|---|
| Linux + discrete GPU | `pytest -q` | the baseline |
| macOS + Metal | `ssh empire`, see `docs/macos-test-machine.md` | threadgroup limits, kernel selection |
| NumPy 1.x | venv with `numpy<2` | `uint64 + int` promoting to float64 |
| low descriptor limit | `bash -c "ulimit -n 256; pytest -q"` | the Vulkan context leak |

A fifth that costs nothing and is worth adding to CI: `ulimit -n 256` on the
existing Linux job.

## Standing measurements

`tools/health.py` prints all of these. Numbers below are from `6b7e6f3` on a
Radeon 8060S; they are the baseline to beat, not targets in themselves.

```
backend duplication            6 methods written twice (destroy hier_peaks
                               peaks pipeline read write)
filter-class duplication       6 overrides (__init__ _ensure _run_gpu
                               _run_series_gpu _start_gpu run_series)
environment knobs              33 total, 27 untested, 20 undocumented
thin API coverage              MatchedFilter.nbins,
                               HierarchicalFilter.set_coarse_margin
magnitude plumbing             ap_peak still carries it; 4 buffers allocated
descriptors per dropped filter +0   (was +4 before fe24469)
GPU run_series host fraction   38-47% of the call, serial with the device
```

---

## Backlog

Ordered by measured size of the gap, not by how interesting the work is.

### 0. The GPU hierarchical `run_series` fires where the CPU dismisses

**Correctness, so it outranks everything below.** Found by reading the code
for item D: the two `_run_series_gpu` implementations disagree about the
`1/n` the C applies on the way in. The flat one divides; the hierarchical
one does not.

On pure noise with a gate calibrated at `snr=5.5` the correct answer is
nothing, and the CPU gives nothing. The GPU reports peaks at every block
count tried (1, 2, 3, 4, 5, 6, 8, 12), at magnitudes around n times the flat
filter's on the same data -- 0.061 to 0.087 after dividing by n=4096,
against the flat filter's 0.0742. Values that size sail past the coarse
gate, so every pair escalates and is reported.

Reproducer: `tests/test_hier_series_scale.py`, xfail, strict=False.

**Not yet root-caused, and one thing contradicts the obvious explanation.**
If the error were a uniform factor of n, `test_run_series_agrees_with_the_cpu`
would fail -- it compares magnitudes where both fired, and it passes. So
either the scaling is compensated somewhere on the injected-signal path, or
the factor is not uniform. Resolve that before changing the `1/n`.

Next step: compare `_gpu_hier`'s inputs between the `run()` route (spectra
the caller pre-divided) and the `run_series` route (spectra built in the
method), on the same blocks. One of them is scaled differently and the
difference is the bug.

**Done when:** the xfail flips to a pass without loosening the fixture.

### A. Fewer decisions for the user

**Evidence:** 33 environment knobs, 27 with no test pinning their behaviour,
20 undocumented. Plus `binsize`, `window`, `ndata`, `device`, and for the
hierarchical filter `snr`, `fd`, `band`, `oversample`, `taps`.

The tables already remove most of the hierarchical decisions automatically.
The knobs are the opposite: each is a behaviour that can change silently.

1. **Triage the 33.** Each is one of: a real user control (document and test
   it), a developer switch (move behind `MF_DEV_*` and say so in one place),
   or dead (delete). Target: no undocumented knob that is not `MF_DEV_*`.
2. **Make `device="auto"` the documented default** in the README and the
   tutorial, so the first example a reader meets has no device argument.
3. **Default `binsize` to the whole window.** It already does internally;
   the examples should stop passing it.
4. **`ndata` should not be a tuning parameter.** On the flat path it is both
   the batch height and the `run_series` grouping bound. A user should not
   have to know that; `run_series` can group to a sensible internal cap
   regardless of how the plan was built.

**Done when:** the quickstart runs with `MatchedFilter(n, ndata, ntemplates)`
and `.run()`, no other arguments, and `health.py` reports zero undocumented
non-dev knobs.

### B. The host half of `run_series`

**Evidence:** 38-47% of a GPU `run_series` call is the host-side per-block
forward transform, in a Python loop, **serial with the device**.

The batching win alone is noisy -- measured 1.41x and 1.07x on two runs of
the same probe -- so do not sell this on batching. The real prize is that
nothing currently overlaps host transform, upload, and dispatch.

1. Replace the per-block Python loop with one strided gather and one batched
   `np.fft.fft(..., axis=1)`. Cheap, and it makes step 2 possible.
2. Chunk the blocks and pipeline: transform chunk *k+1* on the host while
   chunk *k* is on the device. Needs the upload to be per-chunk rather than
   per-call.
3. Only then consider moving the forward transform onto the device.

**Done when:** the host fraction in `health.py` is under 15% and the
whole-call time has dropped by a number recorded here.

### C. Blocking and chunking for the N x T product

**Evidence:** not yet measured; this item's first task is to measure it.

The shape is the point: D segments against T templates is D*T work for
D + T of input. The current code uploads everything and dispatches once.

1. **Measure the roofline for the batch**, as `tools/gpu_roofline.py` does
   for the transform: at what (D, T) does the call stop being compute bound?
   Add it to `health.py`.
2. Pick a tile in (D, T) that keeps the working set in cache on the CPU path
   and in L2 on the GPU path, rather than streaming the bank once per
   segment.
3. The CPU path already has `MF_MFTILE`; it is untested and undocumented.
   Either it is the answer here, or it should go.

**Done when:** there is a measured (D, T) curve in this file and a chosen
tile justified by it.

### D. Duplication

**Evidence:** 6 methods written twice across the GPU backends, 6 more
duplicated between the two filter classes. `_run_series_gpu` is a near copy
in both classes -- written that way knowingly, in 505347d, and now due.

1. **One host orchestration, two thin device layers.** `peaks`, `hier_peaks`,
   `destroy`, `pipeline`, `read`, `write` differ only in which API they call.
   Extract the shared sequencing; leave backend-specific buffer and
   dispatch calls behind a small interface.
2. **Collapse `_run_series_gpu`.** The flat and hierarchical versions differ
   in one call (`self._gpu.peaks` vs `self._gpu_hier`) and in nothing else
   structurally.
3. The six test-side helpers were already consolidated into
   `conftest.usable_gpu` and `conftest.vulkan_runs` (c3c8dbd). Keep new ones
   out.

**Done when:** `health.py` reports fewer than 3 duplicated methods per pair,
and the count is watched rather than left to drift.

### E. Cruft

1. **`magnitude`.** `ap_peak` still carries the field, the C still fills it,
   four Python buffers still receive it, and every caller discards it. It is
   what let the CPU and GPU return contracts drift apart unnoticed
   (eda2cea). Removing it changes a public struct, so it is its own change.
   `hmf.c` uses `.magnitude` internally for the gate comparisons, which is
   load-bearing -- move it to a local, do not delete the arithmetic.
2. **The slangpy import in `conftest.py`.** Documented as spike-only. The
   shipped backend dlopens Vulkan itself and slangpy is not a dependency.
   Confirm it changes nothing, then delete the workaround and its comment.
3. **Dead knobs**, from the triage in A.

### F. Test gaps

Ordered by what the gap has already cost.

1. **Cross-path contract tests.** Every backend was checked against a
   numerical reference and never against the other backend through the same
   call, so `raw=True` returning three arrays on one path and two on the
   rest was invisible. `test_run_series_flat.py` now does this for arity;
   extend it to shapes, dtypes, and error types.
2. **Resource tests.** The descriptor leak had no check until it had caused
   a full afternoon of misdiagnosis. `health.py` measures it and
   `test_a_dropped_gpu_filter_gives_its_descriptors_back` pins it. Add the
   same shape of test for device memory.
3. **`MatchedFilter.nbins` and `set_coarse_margin`** are each mentioned once
   in the suite.
4. **The 27 unpinned knobs.** Anything surviving triage in A needs a test
   that fails if it stops working.
5. **`test_both_staging_variants_agree` has no Apple host**, by construction:
   the preferred build wants 64 KB of threadgroup memory and no Apple GPU
   has it. Left as a known hole, recorded so it is not rediscovered.

### G. Platform synchronisation

**Evidence:** `LDS_CAP` and `METAL_CAP` are two hand-maintained tables. The
split was correct -- CH=16 is 2.01x on an M2 and a 31% loss on a Radeon
(0c69ba3) -- but it is two tables keyed by hand, and a third device means a
third.

1. **Make the cap a function of device capability, not device name.** The M2
   wants one chunk because it has little threadgroup memory per core; the
   Radeon wants small staging because it has enough to keep several
   workgroups resident. That is a rule, and a rule generalises where a table
   does not.
2. **`tools/gpu_roofline.py` is Metal-only.** Port it to Vulkan so every
   device can be placed against its own measured ceiling. Until then the
   Radeon's achieved rate is known and its achievable rate is not.
3. **Per-device cost tables** now exist for `gfx11` and `apple`. The apple
   key does not distinguish M-series generations; an M4 uses an M2's
   numbers. Decide whether that matters by measuring one.

### H. Cohesion that also buys speed

1. **One Slang source already generates both backends.** Keep it that way;
   every divergence should be a measured trade with the numbers in the
   commit, as the cap split was.
2. **Wave intrinsics.** `WaveShuffle` compiles to `simd_shuffle` on Metal and
   subgroup ops on SPIR-V. Exchange levels whose span stays inside a
   SIMD group can skip threadgroup memory and both barriers entirely. This
   is the one optimisation on the list expected to help *both* backends
   rather than forcing another split.
3. **n=16384 on Apple** runs at 13% of that chip's measured add rate against
   32-52% at every shorter length, on a forced 1024-thread allocation that
   spills. An R=32 decomposition is the candidate.

---

## Known open items not in the loop

- `v0.1.0a2` is tagged at `eda2cea`, which predates the NumPy 1 fix, the GPU
  gating and the descriptor leak fix.
- The false-dismissal budget: 8/893 omissions, 0.90% against `fd=1e-3`,
  reported from the pycbc side. A violated guarantee outranks everything
  above; confirm it first.
- Band selection at snr 6.0 did not reproduce on a homogeneous template
  bank. The open question is whether the accuracy parameterisation assumes
  bank homogeneity, which would be a larger finding than the original
  report.
