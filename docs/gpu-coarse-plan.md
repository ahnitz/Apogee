# GPU coarse stage: what we did, and what to do next

Written after a long optimisation pass. Everything here is measured; the
falsified list is as important as the shipped list, because five of the
eight ideas that looked good from the source turned out to be wrong.

## Where it stands

    band   before    now      speedup   % of fp32 peak   issue efficiency
     128   1.911   0.743 ms    2.57x         11%               87%
     256   1.095   1.106       neutral       19%               58%
     512   2.239   1.758 ms    1.28x         20%               59%
    1024   4.348   3.814 ms    1.14x         24%               61%

Against fp16 peak the large bands sit near 10%. The coarse stage is the
right target: at SNR 5-6 with a ~2048 window the search is dismissal
dominated, so this is ~90% of a hierarchical run.

## Shipped, and why each worked

1. **One-bin specialisation.** The coarse gate reports one value per pair
   by construction (cidx/cval are sized `pairs`), so nbins is 1 and the
   per-bin seed loop, bin index arithmetic, nbins>1 atomic branch, bin term
   in the output index and per-bin -1 sweep are all dead. +13-14% at the
   large bands -- the ONLY change that moved them.
2. **PPG = 512/band.** WG = band/16 makes a workgroup smaller than a wave
   below band 512; PPG packs pairs to fill the lanes. Large gain at 128.
3. **TILE_T=4 at band 512.** The thread's data slice is hoisted into
   registers and reused across 4 templates: loads per tile go 2T -> 1+T.
4. **Packed fp16 coarse banks.** Neutral on time, but halves L1
   oversubscription (4x -> 2x) and is the prerequisite for half registers.
5. **Dead gated pipeline removed.** 256 VGPR, 18 spilled, 2304 B scratch --
   compiled for every plan and never dispatched.

The pattern: **every change that DELETED work paid; every change that tried
to make the same work cheaper did not.**

## Falsified by measurement -- do not retry without new evidence

    fp16 loads alone              no gain     not bandwidth bound
    half2 LDS staging alone       neutral     LDS was not the binding limit
    permuted banks, block-of-16   -17%        destroys coalescing
    permuted banks + uint4        -17%        same
    2D KxK tile, K=2              1.07x       worse than 1xK
    2D KxK tile, K=4              -5.6x       register spill
    want[]/twiddle hoist          neutral     compiler already CSEs it
    [loop] instead of [unroll]    -15%        lost ILP costs more than regs
    myMag[16] -> liveMask         -7%         216->96 VGPR, still slower
    drop barrier on 1-wave group  BROKEN      61 test failures

## The diagnostic facts everything below rests on

From `RADV_DEBUG=shaderstats` and `RADV_DEBUG=asm` (the two reads that
produced durable facts after five source-level models failed):

  * **216 VGPRs** -> 7 waves/SIMD -> 44% occupancy. REGISTER PRESSURE
    binds, not the workgroup cap.
  * **Instruction mix, 8456 total:** 928 packed fp16, **789 SCALAR fp16 at
    half rate**, 598 fp32, 933 addressing, 1174 stalls/control.
  * The scalar half ops exist because `cmul` is a CROSS pattern that cannot
    lower to elementwise `v_pk_*`. **Half the fp16 arithmetic never became
    fp16 arithmetic** -- which is why "fp16 math" measured 4%.
  * `s_delay_alu` x451: the compiler inserting dependency stalls, i.e. ILP
    starvation, which is why [loop] lost.

## Plan

### Phase 0 -- unblock. No kernel risk, and it gates everything else.

0a. **Resolve the band-256 discrepancy.** 3.99 ms end-to-end vs ~1.10 ms in
    the sweep, 4x, unexplained. Band 256 is the only band on the tiled
    `coarse_*.spv` path, so it may not run the kernel being optimised. Band
    comparisons feed band SELECTION, so bad data here corrupts the dominant
    lever. Fix before trusting any cross-band number.

0b. ~~**Repair the tuning tools.**~~ DONE. hmf_tune.py, score_cost_rule.py,
    score_selection.py and regen/cost_gpu.py called set_coarse_margin after
    it was removed. `set_coarse_margin` no longer appears anywhere in the
    repository; the margin is expressed as a scale on the measured coarse
    threshold via `_apply_margin`, and the tools run.

0c. **Regenerate the cost tables.** Band selection runs on costs measured
    BEFORE band 128 got 2.57x and band 512 got 1.28x. The relative ordering
    has shifted, so the autotuner may be choosing wrong on every call.
    Since coarse cost dominates a dismissal-heavy search, this is plausibly
    a larger end-to-end win than any remaining kernel work, at zero risk.

### Phase 1 -- cheap, unexplored.

1a. **Sweep R.** R=16 is hardcoded and sets WG = band/R, which caused the
    sub-wave problem at band 128 and drives register pressure everywhere.
    R in {4,8,32} is a build-matrix change, no algorithm change, and it
    attacks both problems PPG and tiling were built to work around.

1b. **Re-tune TILE_T and PPG per band** once R moves, since all three
    interact through the same register and wave budget.

### Phase 2 -- the SoA rewrite. Highest expected value, highest risk.

The only remaining change with direct ISA evidence. Draft is written at
`src/gpu/draft/soa_core.slang`.

Pair ACROSS two independent transforms, never within one:

    re[i] = half2(re of pair A element i, re of pair B element i)
    im[i] = half2(im of pair A element i, im of pair B element i)

Then butterflies are elementwise `v_pk_add_f16`, and a twiddle multiply is
re*wr - im*wi / re*wi + im*wr with the twiddle broadcast -- four v_pk_*,
no swizzle. Three wins:

  * 789 scalar half ops -> ~0
  * the x i rotation in radix-4 becomes a register rename plus a negate,
    where AoS needed a cross-component swizzle. Radix-4 is full of these.
  * |v|^2 stays in half, removing part of the 598 fp32 ops

Register cost is neutral (32 VGPRs for two transforms, what two C r[16]
cost now) and TILE_T already supplies the independent transforms.

**It must land atomically.** An AoS/SoA boundary costs exactly the
gather/scatter being eliminated, so a partial conversion measures worse
than either endpoint. ~240 lines: 9 functions plus the load, stage,
magnitude and peakVal. Verify with shaderstats (VGPR should not move) and
asm (scalar v_*_f16 should approach zero).

### Phase 3 -- deletes work, which is the category that pays here.

3a. **Window pruning.** With a ~2048 of 4096 window, half the coarse
    outputs are computed and discarded. `slotToIndex` already maps the
    register index to the HIGH output bits, so register i of every thread
    holds a contiguous output block -- the skip is WAVE-UNIFORM, which is
    what makes it viable. Skip whole r4 groups in the final dft16.
    Ceiling is ~5%: it only reaches the last stage, and the exchange still
    moves everything. Compile 2-3 window variants and select at plan time;
    a runtime test only gives predication.

3b. **Window mask.** Cheap, independent, and worth more at a half window
    than at a full one, where the mask is all ones.

### Phase 4 -- scheduling, no kernel risk.

4a. **Cross-stage overlap.** coarse -> compact -> refine is serialised by
    global pipeline barriers. Split the batch (we already choose the
    decomposition) so refine(i) overlaps coarse(i+1). The refine dispatch
    is small and occupancy-poor in a dismissal-heavy search -- work that
    should be HIDDEN rather than optimised. Needs a second compute queue;
    interleaving in one queue will not do it.

4b. **run_series pipelining.** It already walks blocks, so the chunking
    exists. Also opens host/device overlap: pack and upload block i+1 while
    the GPU runs block i.

## Method notes carried forward

  * Measure before refactoring: stubbing showed the exchange is 12% and the
    transform is free, which killed a planned multi-transform change before
    it was written.
  * Run-to-run variance is 7-15% here. Report means of >=3; anything inside
    the spread is neutral, not a win.
  * Timing and correctness in the same breath. PPG measured 2.27x while
    silently dismissing three quarters of the signal.
  * Read the compiled output after two mispredictions, not after five.

## Phase 0a result: RESOLVED -- it was a benchmark-harness bug (see below)

Measured, 262144 pairs, coarse only (threshold 1e9, refine_rate 0 in every
case so nothing escalates):

    band   random templates   inspiral templates
     256        1.108 ms           3.985 ms       <- 3.6x slower
     512        1.433 ms           1.612 ms       <- 1.1x

**Band 256 is 2.4x SLOWER than band 512 on realistic templates while doing
half the work.** On random templates the ordering is correct (256 cheaper
than 512), so every benchmark in this effort -- all of which used random
templates -- masked it.

Ruled out:
  * escalation: refine_rate is 0.0000 throughout, threshold is 1e9
  * denormals: the coarse band of an inspiral template has median |v| of
    4.8e-2 and ZERO values below the fp32 or fp16 tiny threshold
  * the tiled coarse_256.spv path: disabling _COARSE_TILE changes it by 1%
    (3.985 -> 3.935), so the special path is not the cause

Still unexplained. The coarse kernel should be data-INDEPENDENT with the
gate closed: same loads, same transform, same barriers, and the peak
writeback is predicated off. Something in this configuration is not.

**This blocks Phase 0c.** Band 256 is a band the autotuner can select, and
cost-table regeneration would record 3.985 ms as its cost -- which is
either a genuine property that band selection SHOULD see, or an artifact
that would poison the table. Regenerating before knowing which would bake
the wrong number into every future selection.

Next diagnostic: RADV_DEBUG=shaderstats and asm for band 256 against band
512 on the SAME template set, and a counter check that both dispatch the
group count they should -- band 256 runs PPG=2 (131072 groups) against band
512 at TILE_T=4 (65536 groups), so the launch counts differ by 2x and that
is the first thing to confirm rather than assume.

## Phase 0a, resolved: set_coarse_threshold was ignored on the GPU

The band-256 "anomaly" was an artifact of my own harness, not a property
of the kernel.

**The autotuning route was never involved.** It reads the threshold from
the calibration table and the band from the cost table, and that was
correct throughout. The bug was in the MANUAL OVERRIDE: _gpu_calibration
went straight to choose_threshold and never consulted self._cal_thr, so
set_coarse_threshold -- the documented way to opt out of the tables -- was
silently discarded on the GPU while working on the CPU.

Benchmarks used set_coarse_threshold(1e9) to close the gate and measure the
coarse stage alone. The GPU ignored it and kept refining, and inspiral
templates -- which are matched to the inspiral reference -- escalate far
more than random ones. Hence a 3.9x "penalty" at band 256 that was really
refinement work.

Fixed: _cal_thr is honoured on both the table path and the CPU-plan
fallback, and added to the _gcal cache key so a cached result from before
the call is not reused. With the gate genuinely closed:

    band   random   inspiral   penalty
     128   0.737    0.718 ms    0.97x
     256   1.095    1.111 ms    1.02x
     512   1.774    1.929 ms    1.09x
    1024   3.404    3.359 ms    0.99x

Data-independent, as a coarse pass should be.

Two consequences:

  * **Phase 0c is unblocked.** There is no band-256 pathology to bake into
    a regenerated cost table.
  * **The earlier optimisation numbers stand.** They all used random
    templates, which escalate so rarely that the gate was closed in
    practice even though the override was being dropped.

And a user-facing bug is fixed on the way: an explicit threshold now
reaches both backends instead of one.
