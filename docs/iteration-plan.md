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
filter-class duplication       6 overrides, but _run_series_gpu is now ONE
                               implementation; the override is a 3-line hook
environment knobs              33 total, 27 untested, 20 undocumented
thin API coverage              MatchedFilter.nbins,
                               HierarchicalFilter.set_coarse_margin
magnitude plumbing             ap_peak still carries it; 4 buffers allocated
descriptors per dropped filter +0   (was +4 before fe24469)
GPU run_series host transform  1.38x faster batched (round 3); still
                               24-46% of the call and still serial
```

---

## Backlog

Ordered by measured size of the gap, not by how interesting the work is.

### 0. GPU hierarchical `run_series` scaling -- DONE (round 2)

The hierarchical `_run_series_gpu` omitted the `1/n` the C applies on the
way in. `_gpu_hier` received `|D|max 304.633` by that route against
`0.0743734` by `run()` on the same blocks: a ratio of exactly 4096. The
gate therefore saw every pair as enormous and escalated all of them.

**The contradiction that held it up for a round resolved into a second
bug.** `test_run_series_agrees_with_the_cpu` compares magnitudes and passed
throughout, which a uniform factor of n should not survive. It passed
because it was **vacuous**: its series was never scaled to unit-variance
output, so the filter saw peaks around 1e-5 against a gate calibrated at
`snr=5.0`, nothing fired on either device, and every assertion compared two
empty selections. It had checked nothing since it was written.

Three things were wrong, each hiding the next:

1. the missing `1/n` (the bug),
2. the unscaled fixture (why no test saw it),
3. `threshold=0.0` in the comparison (why the fixed fixture still failed) --
   below `snr` the GPU legitimately reports a superset, escalating the whole
   interpolation window where the CPU interpolates. At threshold 0 it fires
   52 slots to the CPU's 4, which measures the design. At 5.0 both give 4
   and agree.

A fourth was mine: the first injection used the whitened form
`unit = H/|H|^2`, whose spectrum is `1/conj(H)` and so puts its power where
the template is weakest. The matched filter reports the designed SNR but the
coarse band carries almost none of it, so the gate dismisses for the right
reason. A signal the filter is designed not to find cannot test agreement.
The fixture now injects a scaled copy of the template.

`tests/test_hier_series_scale.py` passes rather than xfails. The fixture is
guarded with `assert fired.any()`.

417 passed on the Radeon box on NumPy 2.4, NumPy 1.26 and at `ulimit -n
256`; 403 on an M2.

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

**Evidence:** the host-side forward transform is 24-46% of a GPU
`run_series` call and **serial with the device**.

Step 1 landed in round 3, together with D's merge -- the batching had to go
somewhere, and there were two somewheres until the merge. Measured best-of-7
on a Radeon 8060S: host transform 1.38x faster batched (0.79-0.87 ms against
1.09-1.20 ms), stable across three runs.

The earlier figures of 1.41x and then 1.07x for the same change were single
samples. `health.py` now takes best-of-7, which is why the number stopped
moving. **Do not sell this on batching**: 1.38x on a term that is a third of
the call is not the prize. Nothing overlaps host transform, upload and
dispatch, and that is.

1. ~~Replace the per-block Python loop with one strided gather and one
   batched `np.fft.fft(..., axis=1)`.~~ Done, round 3.
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
   dispatch calls behind a small interface. STILL OPEN.
2. ~~**Collapse `_run_series_gpu`.**~~ Done, round 3. One implementation in
   the base class; `HierarchicalFilter` overrides a three-line
   `_series_window` hook and nothing else. This is the duplication that
   produced round 0's bug -- the two copies drifted and one lost its `1/n` --
   so the merge is the fix for the cause, where round 2 fixed the symptom.
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

## fp16 coarse stage (next)

Measured, committed under `tools/int8/`: fp16 is free for the coarse stage
-- peak error sd 0.0012 sigma, with the gate and the noise escalation equal
to float to three digits (4.300 / 0.0675). It beats bf16 by 9x and needs no
table regeneration, so CPU and GPU can share one accuracy table. int8 is
viable but needs its own recalibration AND a static clip at 6-8 sigma; at
4 sigma it clips the signal peak and costs 3.6x escalation.

Coarse cost is linear in coarse bytes above band 256 on the 8060S
(1.120 / 2.237 / 4.349 ms at band 256 / 512 / 1024). That is the headroom.

The design point that makes this easy: **the coarse stage is a gate, not a
detector.** It does not need per-bin peaks. It needs "does anything in the
window clear the threshold" -- one WaveActiveMax plus a start/end mask --
because the fine stage re-derives localisation on the survivors anyway.

That matters because `groupshared uint stg[CH*WG*2]` in `tierb.slang:57` is
aliased as a per-bin peak table (275-323), and that aliasing was the only
thing blocking half2 packing. Drop the bin machinery from the COARSE kernel
and the constraint disappears: no `nbins <= CAP` proof, no single-bin
variant, and the stage halves from 8 KB to 4 KB. The bin loops must stay in
the flat/fine kernel, where per-bin peaks are the actual output.

Steps:
  1. Confirm the coarse path's output is used only for the gate decision,
     not for reporting bins. This is the one assumption above that is NOT
     yet verified.
  2. Strip the bin machinery from the coarse kernel; keep it in flat/fine.
  3. half2 staging: stg[CAP], f32tof16/f16tof32 in stgPut/stgGet.
  4. Rebuild SPIR-V, run the GPU tests, re-measure the band sweep.

Watch band 128: it costs 1.676 ms, MORE than band 256's 1.120. Cost is not
monotonic in work below 256, which points at an occupancy or launch floor.
LDS is what caps workgroups per CU, so step 3 is the change that should move
it -- and whether it does tells us if fp16's win is bandwidth alone or
bandwidth plus occupancy. Whatever that floor is, it caps the return.

### Roofline: why fp16 alone cannot reach the target

Measured on the 8060S, coarse-only, band 512, 512x512 pairs, 2.196 ms:

    work 6.85 GFLOP   traffic 2.15 GB
    achieved 3.12 TFLOP/s   978 GB/s
    arithmetic intensity 3.19 FLOP/byte

That is ~21% of this part's ~14.8 TFLOP/s fp32 peak, and the kernel is
BANDWIDTH bound, not compute bound. At AI 3.19, sustaining 50 TOPS would
demand 15.7 TB/s. No precision change reaches that: fp16 halves traffic and
buys ~2x, landing near 6 TFLOP/s.

The lever is arithmetic intensity, and it is reuse. The FFT (5*N*log2(N) =
23040 flop/pair) dwarfs the correlation (3072) and is per-pair regardless,
so tiling does not cut work -- it amortises LOADS over K^2 FFTs:

    scheme            loads    FFTs    AI fp32   AI fp16
    now (1 pair/wg)   2 vec      1       3.2       6.4
    8x8 tile         16 vec     64      25.5      51
    16x16 tile       32 vec    256      51       102

**fp16 + an 8x8 tile puts AI near 51 FLOP/byte, which at ~1 TB/s sustains
~50 TFLOP/s.** Neither change gets there alone. That is the target config.

### Measured this round (all reverted; main is green)

  * **LDS half2 staging: NEUTRAL.** A/B at bands 128-4096, differences in
    both directions and within noise. Occupancy is not LDS-limited at these
    sizes -- the coarse stage is 2-4 KB, far under what caps waves/CU. The
    f32tof16 conversions roughly cancel the saving. Do not revisit without
    a reason beyond "LDS is smaller".

  * **Band 128 is NOT a launch or LDS floor.** `WG = NLEN/16`, so band 128
    runs 8-thread workgroups against wave32 -- 25% lane utilisation, and
    3.5x worse per unit work. 256 -> WG 16, 512 -> WG 32. The fix is
    packing multiple FFTs per threadgroup so the wave is full, which is the
    same change the tiling above wants.

  * **fp16 global storage is blocked by a role collision, not by numerics.**
    Ranges are benign (no over/underflow; template dynamic range 22, fp16
    rounding error 1.8e-4). But `fusedTierB` serves TWO roles: the flat
    filter, reading full-precision data/tmpl, AND the untiled coarse stage,
    reading cdata/ct0. Keying the element format on the entry name therefore
    changes both, and the untiled path is the common one -- `_COARSE_TILE`
    tiles only band 256. Packing the buffers made every coarse peak read as
    -1: not precision, just a kernel reading 4-byte elements as 8-byte ones.

    Fix: build a SUFFIXED coarse variant of fusedTierB compiled for the
    packed format, and have the loader pick it for the coarse role only.
    The kernel side is already understood -- one typedef, one `cload`, and
    the single read site at tierb.slang:247.

### Where the coarse stage actually loses 5.7x (measured)

Per-pair cost at band 512, coarse only, varying the pair count:

     4096 pairs  49.19 ns/pair
    16384 pairs  14.84 ns/pair
    65536 pairs   9.57 ns/pair
   262144 pairs   9.52 ns/pair
   affine: 8.89 ns/pair marginal + 0.165 ms fixed

Theoretical compute per pair at fp32 peak is 1.56 ns (23k flop). The
marginal cost is 8.89 ns and STAYS 5.7x off as pairs grow, while the fixed
term is only 0.165 ms. That rules out, by measurement:

  * bandwidth -- halving the coarse element changed nothing (see above)
  * launch overhead -- the fixed term is small, not the 0.75 ms that
    262144 launches at 2.85 ns would imply
  * occupancy from too few workgroups -- 262144 of them is not too few

What is left is the per-pair kernel. `WG = band/16` with ONE pair per
workgroup makes a workgroup exactly one wave32 at band 512. The transform
is then a serial chain of stages, each with an LDS round-trip and a
barrier, run by a lone wave with NO independent work to overlap. It eats
the exchange latency exposed, once per stage.

### Why fp16 matters, and it is not the bytes

half2 halves REGISTER occupancy per point: R=16 complex goes from 32 VGPRs
to 16. That buys either twice the points per thread, or several independent
FFTs resident in registers at once -- and independent transforms are
exactly the ILP needed to cover each other's exchange latency. At small
bands enough of the transform fits in registers that the LDS exchange
disappears rather than being hidden: n=256 as 4x4 in register space, n=512
as 2x2.

So the packed coarse inputs already landed are not a failed bandwidth
optimisation -- they are the input format that lets the transform stay in
half all the way into registers. Measuring them by bandwidth was the
mistake; the gain is register capacity.

Next: half2 through the coarse butterflies (cmul/cmulConj/r4/dft*), then
multiple independent FFTs per thread in the freed register space.

### half2 arithmetic: 4%, and it confirms the diagnosis a third time

The coarse transform now runs in half2 under COARSE16 -- typedef C/CS over
cmul, cmulConj, r4, dft2/4/8/16, innermost, exchange. Native fp16 is really
emitted: the SPIR-V carries capability 9 (Float16), which the fp32 build
does not. Magnitudes and peak output stay float, so the gate comparison and
the reported value are unchanged in type.

    per pair, band 512:  fp32 8.89 ns  ->  half2 8.52 ns   (4%)

Against a 0.78 ns/pair fp16 peak that is still 11x off. Three levers have
now been measured:

    fp16 loads  (half the traffic)  -> nothing
    fp16 math   (half the ALU work) -> 4%
    fewer bytes in LDS              -> nothing

None of them is the constraint, which leaves only the dependency structure:
a lone wave walking a serial chain of FFT stages, each behind a barrier and
an LDS round-trip, with no independent work to overlap. Halving the
arithmetic cannot help a wave that is stalled on an exchange.

So the remaining step is the one that targets it directly, and half2 is
what makes it fit: MULTIPLE INDEPENDENT TRANSFORMS PER THREAD. r[16] in
half2 costs 16 VGPRs where fp32 cost 32, so two or four transforms sit
where one did. Their exchanges interleave and cover each other's latency;
at n=256 four fit in register space (4x4) and the exchange can go away
entirely, at n=512 two (2x2).

This is the change that should move the number. Everything before it was
either a prerequisite (packed inputs, half2 registers) or a falsified
hypothesis (bandwidth, launch, occupancy-from-count, LDS size).

### PPG: fill the wave. 2.3x at band 128, and the rule that bounds it

`WG = band/16` with one pair per workgroup means a band under 512 runs a
workgroup SMALLER than one wave32 -- at band 128, eight threads on a
32-lane wave, three quarters of it idle. PPG packs 512/band pairs into a
group so the lanes are full, each pair getting its own LDS region via
_stgBase, and at band 512 one pair is still exactly one wave so
WaveActiveMax keeps reducing per pair.

    band   baseline   now      (means of 3 runs)
     128    1.911    0.846     2.26x FASTER
     256    1.095    1.107     neutral
     512    2.239    2.390     -7%, inside the noise
    1024    4.348    4.487     -3%, inside the noise

The rule is PPG = 512/band, and it is bounded by exactly what it fixes:
past a full wave there is nothing left to fill. PPG=4 at band 512 changed
nothing and at band 1024 regressed 4.348 -> 5.006, because the per-group
stage grows with PPG while the wave was already full. So the half-width
coarse path is gated to band < 256 -- everywhere else keeps the fp32
kernel, which measured faster.

Two traps this round, both of which produced confident wrong readings:

  * **Run-to-run variance is ~15% at band 128 and ~7% at 512.** Single
    runs supported the opposite conclusion at 256 and 1024. Every number
    above is a mean of three, and the -7%/-3% rows are reported as noise
    rather than as regressions because they are inside that spread.

  * **A PPG=1 build still paid for PPG.** The _sub divide and the
    _stgBase multiply are identity at PPG=1, but the compiler cannot prove
    _sub == 0, and leaving them in cost ~20% at band 512 -- on the DEFAULT
    path, which does not use PPG at all. They are now behind `#if PPG == 1`.
    Computing them into locals matters too: splitting the filterPair CALL
    across #if/#else/#endif failed the preprocessor at n=64.

Still 5.5x off fp16 peak at band 512 (8.5 ns/pair against 0.78). Filling
the wave was worth 2.3x where the wave was empty and nothing where it was
already full, so the remaining gap at full-wave bands is NOT lane
utilisation. It is still the serial exchange chain, and the untried lever
is several independent transforms per THREAD rather than per workgroup.

### Do NOT drop the execution barrier on the single-wave path

The exchange runs two GroupMemoryBarrierWithGroupSync per level and R/CH=1
at band 512, so on a 32-thread group they look like pure overhead: lanes of
one wave are in lockstep, so only the memory fence should be needed.
Replacing them with GroupMemoryBarrier() where WG*PPG <= 32 gives
**61 test failures**.

Vulkan does not guarantee that a 32-thread workgroup occupies a single
wave, and nothing in the memory model makes the LDS writes visible to the
other lanes without the execution sync. The subgroup size is a device
property, not something the group width implies -- a driver may pick wave64
or split the group, and then the exchange reads values that were never
written.

It was not worth it even if it had been sound: band 512 moved 2.390 ->
2.318 ms, inside the ~7% run-to-run spread. If this is ever revisited it
has to go through the subgroup extensions with a real size query, not an
assumption about the group width.

### The coarse stage is bound by LOAD INSTRUCTION COUNT, not bytes or math

Measured by stubbing pieces of the kernel out (results deliberately wrong,
timing only), band 512, 262144 pairs, baseline 2.239 ms:

    exchange deleted entirely     1.981 ms   -> the whole exchange is 12%
    innermost() deleted entirely  2.34  ms   -> the transform is FREE

The butterflies cost nothing and the LDS exchange costs 12%, so ~88% is the
global loads. That is why every precision change so far returned nothing:

    a float2 load is ONE 8-byte dwordx2
    the packed uint32 is ONE 4-byte dword

Same instruction count, half the bytes. If the limit is the RATE OF LOAD
INSTRUCTIONS rather than bytes moved, halving the element is a no-op -- and
that is exactly what was measured, three times.

Per pair: 2*512 complex loads / 32 threads = 32 loads per thread; 268M
loads in ~1.98 ms is ~135 G loads/s against roughly 232 G/s of issue
capacity on this part. The right order to be the limit.

**So the fp16 win is not half the bytes, it is half the LOADS**: pack TWO
complex per 8-byte load (uint2 / four halves) so each load instruction
fetches two points. That halves the load count, which is the quantity that
actually binds. The current packing was one complex per uint32 and
therefore could never have helped.

Also settled: TPT (several transforms per thread) is capped at ~12%,
because all it can hide is the exchange. Not worth the restructuring of
exchange() it would need. Measure before refactoring.

Caveat: the no-load variant timed 23.8 ms and is NOT usable -- a constant
stub makes every lane produce the same magnitude and the InterlockedMax
peak table serialises on contention. Discarded rather than reported.

#### How to halve (quarter) the loads: permute the coarse banks on upload

The blocker is the index pattern. `idx = tid + WG*n2`, so a thread's R
successive loads are WG apart -- coalesced ACROSS the wave for a given n2,
but never adjacent WITHIN a thread, so two of them cannot fold into one
wide load as they stand.

The host builds cdata/ct0, so it can store them in consumption order:
thread tid's R=16 complex values contiguous. Then, packed at 4 bytes per
complex, one thread's whole working set is 16*4 = **64 bytes, exactly one
cache line**, fetched as 4 x uint4 instead of 16 scalar loads.

    loads per thread per buffer:  16  ->  4
    loads per pair:               32  ->  8

Coalescing does not suffer the way it looks like it should: each thread
touches exactly one full 64-byte line and a wave touches 32 distinct lines,
all fully consumed. That is the same bytes with a quarter of the
instructions -- and instructions are what binds.

This is the prestaging the N x M pair grid pays for once: each coarse row
is permuted on upload and reused across every pair that references it.

Order of work:
  1. permute cdata/ct0 in _pack_half2 on the host (pure numpy reshape)
  2. load as uint4 in the coarse kernel, unpack 2 complex per 32 bits
  3. keep the fp32 path untouched -- it is the flat filter's, and it
     measured faster at full-wave bands

### Permuted banks and wide loads: both REJECTED by measurement

Two attempts to cut load instructions, both reverted:

    band                    128     256     512    1024
    baseline (old coarse)  1.911   1.095   2.239   4.348 ms
    permuted, scalar loads 0.836   1.162   2.654   4.558
    permuted, uint4 loads  0.803   1.139   2.628   4.556

Permuting so a thread's R values are contiguous, then loading 4 complex per
uint4 -- 4 load instructions per buffer where the scalar form needs 16 --
made band 512 ~17% SLOWER, not faster.

The reason is that the ORIGINAL layout was already optimal. `idx = tid +
WG*n2` has the 32 lanes of a wave reading consecutive addresses, so one
instruction touches 4 full cache lines, perfectly coalesced. Permuting puts
the lanes 64 bytes apart: 32 distinct lines per instruction, each only
partly used by that instruction. Fewer instructions, far worse coalescing,
and coalescing won.

So the load-issue-rate hypothesis is dead too. The stubbing result stands --
88% of the kernel is the loads, the exchange is 12%, the arithmetic is free
-- but the loads are already issued as efficiently as this layout allows.

What that leaves is not making the loads cheaper but making them FEWER, and
the pair grid is where the redundancy is: every data row is read by all
ntemplates pairs and every template row by all ndata pairs. A workgroup
that handles one data row against K templates loads 1+K rows instead of 2K.
THAT is how global loads approach free, and it is different from PPG, which
packs independent pairs each carrying their own two loads.

### Block-of-4 pre-permutation: also rejected, and what is left standing

Permuting blocked by FOUR (the uint4 width) rather than by R gives loads
that are wide AND coalesced at once -- lane tid reads four consecutive
complex while adjacent lanes read adjacent uint4s, 32 x 16 B = 8 fully used
cache lines per instruction. It is the layout that should have worked.

    band 512:  baseline 2.239   block-of-4 2.622 ms   still ~17% slower

Timing is sound: uploads happen only when the batch is first built, so the
permutation is preparation and sits outside the timed loop. It was checked
rather than assumed.

Stubbing, band 512, baseline 2.239 ms (results wrong, timing only):

    exchange deleted        1.981   12%
    innermost() deleted     2.34    free
    slotToIndex deleted     2.285   free

So the transform, the digit reversal and the exchange together are ~12%,
and no load layout tried -- plain, permuted-by-16, permuted-by-4, scalar,
uint4 -- moves the remainder. Note "88% is the loads" was an inference by
ELIMINATION, never a measurement: the no-load variant timed 23.8 ms because
a constant stub makes every lane produce the same magnitude and the peak
table serialises on atomics. That inference is the weakest link left and
deserves a proper test (vary only the band with work held fixed) before
more layout work.

Eliminated by measurement this session: bandwidth, launch overhead,
occupancy-from-count, LDS footprint, ALU precision, lane utilisation at
full-wave bands, load instruction count, load coalescing, exchange latency
(capped at 12%, which also kills TPT), and digit reversal.

The untouched lever is the one the pair GRID offers: every data row is read
by all ntemplates pairs and every template by all ndata. One data row
against K templates costs 1+K row loads instead of 2K, with the shared row
staged once in LDS. PPG does not do this -- it packs independent pairs that
each still carry their own two loads. That is the next thing to build.

### Template tiling works, and register pressure is the price

The kernel never tiled. `d = pair/ntmpl`, `t = pair%ntmpl`, one pair per
workgroup, each loading BOTH rows -- so every data row was re-read by all
ntmpl pairs referencing it. The batched grid was in the API and unused.

Prototyped: hoist this thread's data slice into `C dreg[16]`, loop TILE_T
consecutive pairs (which share a data row by construction), dispatch
pairs/TILE_T. Loads go from 2*TILE_T*R to R + TILE_T*R -- 144 against 256
at TILE_T=8.

    band                    128     256     512    1024
    baseline               1.911   1.095   2.239   4.348 ms
    refactor, TILE_T=1     0.908   1.113   3.177   9.664
    tiled,    TILE_T=8     0.707   1.125   2.338   7.295

Read the middle row first: at TILE_T=1 the refactor is PURE COST -- same
loads, plus 16 live registers for dreg -- and it costs 42% at band 512 and
2.2x at band 1024, where WG=64 already strains the register file. Tiling
then earns most of that back (3.177 -> 2.338 at band 512), which proves the
load saving is real and substantial.

But it only breaks even against baseline, because dreg in fp32 costs 32
VGPRs. The fix is the one thing not yet combined with it: under COARSE16 a
C is half2, so dreg costs 16 VGPRs instead of 32. fp16 is what makes the
tile affordable -- not bandwidth, not ALU rate, REGISTER FOOTPRINT for the
reused row.

Band 128 already gains outright: 1.911 -> 0.707, 2.70x, up from 2.44x with
PPG alone.

Next: TILE_T with COARSE16 registers at band 512, and a tile that grows
only while occupancy holds -- TILE_T=8 at band 1024 is clearly past it.

### Operation accounting, and the design that reaches 4x

Per THREAD per PAIR at band 512 (WG=32, R=16, NLEVELS=2):

    FFT butterflies            360   VALU  <- useful
    correlation cmulConj        48   VALU  <- useful
    slotToIndex x2 passes      288   VALU
    exchange index math        192   VALU
    want[] construction        160   VALU
    magnitude + window          80   VALU
    global loads                32   VMEM
    LDS write + read            64   LDS
    barriers                     4

    VALU total 1128, of which 408 (36%) is the actual transform.

Sanity: 1128 wave-instructions x 262144 pairs / (40 CU x 2 SIMD x 2.9 GHz)
= 1.27 ms issue-bound against 2.30 ms measured, so ~55% issue efficiency.
Stripping to the useful 408 gives 0.46 ms, which IS the fp32 peak figure,
as it must be. The model is the right order.

**64% of the instructions are addressing, not arithmetic** -- and all of it
is a property of the LAYOUT and the OUTPUT CONTRACT, both of which we
choose. Three deletions, largest first:

  1. **The coarse stage never needs an index, only a maximum.** A max is
     order-independent, and the tiled coarse path already binds only
     [cdata, ct0, cval] -- no cidx. slotToIndex is computed and discarded.
     Its one real consumer is the window test.

  2. **The window is a precomputed MASK.** live = idx in [winStart, winEnd)
     depends on tid and the register slot, never on the pair or template.
     Build a 16-bit mask once per workgroup, then per pair it is a select
     before the max. That removes slotToIndex from the per-pair path
     ENTIRELY rather than leaving it unused -- 288 -> ~0.

  3. **want[] and the exchange index math are the layout talking.** They
     compute where each register's value lives after each level's shuffle.
     Because the banks are pre-arranged and the tile fixes the access
     pattern, the LDS layout can be chosen so each level reads CONTIGUOUSLY
     -- stgGet(base + j*WG + tid) with base a loop constant. The shuffle
     moves into the pre-arrangement, paid once per row on upload and
     amortised over the whole N x M grid.

  4. Whatever survives is loop-invariant across the tile: it depends on tid
     and the level, so TILE_T=8 divides it by eight.

                                          VALU/pair   vs now
    now                                      1128      1.00x
    window mask (kills slotToIndex)           840      1.34x
    + linear-layout exchange                  488      2.31x
    + hoist remainder across TILE_T=8        ~418      2.70x
    + half2 on the useful 408                ~214      5.3x

Two constraints this design MUST respect, both learned the hard way:

  * **Coalescing beats instruction count.** Block-of-16 and block-of-4
    pre-permutations both LOST (17% at band 512) because they put lanes a
    cache line apart. Any pre-arrangement has to keep adjacent lanes on
    adjacent addresses. This is a design input, not something to discover
    afterwards.

  * **The stub measurements are suspect.** Deleting slotToIndex measured NO
    gain despite being 25% of instructions. Either the kernel is stall-bound
    at 55% issue efficiency -- in which case cutting instructions pays
    nothing until the stalls go -- or the stub was dead-code eliminated,
    which this repo's own machine-notes warn about. RESOLVE THIS FIRST;
    the 2.70x above is not bankable until it is explained.

### Per-band accounting: where the remaining 3-3.7x is

Per THREAD per PAIR, VALU:

    band  WG  LV  useful  slotIdx  want[]  exchIdx  mag/win  TOTAL  useful%
     128   8   1     272      192      80       96       80    720     38%
     256  16   1     272      192      80       96       80    720     38%
     512  32   2     496      288     160      192       80   1216     41%
    1024  64   2     496      288     160      192       80   1216     41%

Only ~40% of the instructions are the transform. The overhead is LARGER at
the big bands in absolute terms because NLEVELS goes 1 -> 2 at band 512,
which doubles want[] and the exchange index math and grows NDIG -- while
useful work per thread stays flat, since R is always 16. That is why the
removal multiplier is better there:

    band   now   -slotIdx  -want/exch  +half2   total
     128   720      528         352      216    3.33x
     256   720      528         352      216    3.33x
     512  1216      928         576      328    3.71x
    1024  1216      928         576      328    3.71x

Three steps, each removing work rather than restructuring it:
  1. window as a precomputed MASK -> slotToIndex leaves the per-pair path
  2. pre-arranged layout -> the exchange reads contiguously, want[] goes
  3. half2 on what remains

Constraint carried forward: coalescing beats instruction count. Both
pre-permutations tried so far LOST ~17% at band 512 by putting lanes a
cache line apart. Lane adjacency is an input to the layout, not a
discovery afterwards.

#### slotToIndex collapses from both ends (288 VALU/pair -> ~0)

Three independent reductions, not one:

  1. **The coarse path needs no index.** The tiled coarse kernel binds
     [cdata, ct0, cval] -- no cidx -- and a maximum is order-independent.
     The writeback's slotToIndex computes a value nothing reads. Deletion,
     not optimisation.

  2. **The window mask removes the other consumer**, and the mask is per
     THREAD, not per pair: liveness depends on tid and the register slot
     only. One 16-bit register, built once, then a select before the max.

  3. **Where an index is genuinely needed** (flat / refine), the current
     eager-all-16 shape is wrong twice over:
       * LAZILY -- only the lane that WINS needs its index, and at a real
         threshold that is zero lanes on almost every pair. Cost ~0
         amortised instead of 16 reversals per thread per pair.
       * INCREMENTALLY -- slotToIndex(tid*R + i) for i = 0..15 reverses
         CONSECUTIVE integers, so after the first each next one is a
         reverse-carry increment (~2 instr) rather than a full NDIG-digit
         reversal (~9). 288 -> ~40 even computing all sixteen eagerly.

So on the coarse path the term goes to zero, and elsewhere it drops by ~7x
without changing what is computed.
