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

0b. **Repair the tuning tools.** hmf_tune.py, score_cost_rule.py,
    score_selection.py and regen/cost_gpu.py all call set_coarse_margin,
    removed earlier. They are the only way to regenerate cost tables.

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
