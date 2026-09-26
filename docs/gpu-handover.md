# GPU work: state and next steps

Written at the end of a long optimisation session. `main` is clean and
green: **425 passed, 3 skipped, 1 xfailed**. Everything below is measured
unless it says otherwise.

## 1. BLOCKING BUG: tile baked into the kernel vs the host's dispatch

**Symptom.** The hierarchical GPU filter silently dismisses signal the flat
filter finds. At n=4096, nd=2:

    nt=1   fails at bands 128, 256, 512, 1024   (all)
    nt=2   fails at band 512
    nt=3   fails at bands 128, 256, 512, 1024   (all)

It is not an exception and not a wrong peak -- peaks that ARE reported are
correct. Pairs simply never get visited, so it reads as a working gate.

**Root cause, confirmed.** `tools/build_spirv.py` line ~277:

    "#define TILE_T %d\n" % (..., COARSE_TILE_T.get(n, 1) if coarse16 else 1)

with `COARSE_TILE_T = {128: 2, 256: 2, 512: 4, 1024: 2}`. So the BASE
`tierb_<band>_c16*.spv` kernels carry the band's tile -- **there is no
TILE_T=1 kernel for those bands at all**. When the host cannot use the tile
(it needs `ntemplates % tile == 0`) it drops the DISPATCH to one tile but
still selects a kernel compiled with tile 2 or 4. That kernel walks
`TILE_T` consecutive templates from `p0 = gid.x * TILE_T` and runs off the
end of the bank.

**The fix, attempted and not completed.** Make the tile part of kernel
IDENTITY:

  1. `compile_one(..., tile=1)` -- add the parameter back (it has been lost
     twice now when the file was restored from a backup) and use `tile` in
     the define instead of `COARSE_TILE_T.get(n)`.
  2. Base `_c16`, `_c16p2`, `_c16p4` build at `tile=1`.
  3. Tiled variants build under their own suffix, spelled EXACTLY as the
     host spells it -- "p1" is omitted, so ppg=1 is `_c16t<T>`, not
     `_c16p1t<T>`.
  4. Host (`_vkcompute.py`): guard `_ppg` FIRST, then choose `_tile`
     against the FINAL ppg. Require `nt % _tile == 0` as well as
     `(nd*nt) % (_ppg*_tile) == 0` -- the tile walks TEMPLATES, so the pair
     count dividing is not sufficient (nt=2 with tile=4: 4 % 4 == 0, yet
     the tile still overruns).
  5. Filename must include `t%d` when `_tile > 1`, and the dispatch must be
     `pairs // (_ppg * _tile)` with the SAME `_tile`.

This reduced failures (nt=1 went from four bands to two) but did not close
them. **Unresolved case to start from: nd=2, nt=1, n=2048, band=1024.**
By inspection ppg=1 and tile falls back to 1, so the dispatch should be
exactly right -- meaning either the selection is not doing what it reads
like, or something downstream of it is wrong. Trace that ONE combination
(print the chosen filename, `_ppg`, `_tile`, group count) rather than
sweeping.

## 2. GPU size coverage vs the CPU

GPU lacks, relative to the CPU: **8192/256, 16384/256, 16384/512**. These
are threshold-table refusals, not kernel gaps -- `choose_threshold` now
correctly returns None below the measured hull.

Fix: extend the table at those sizes.

    python tools/regen/threshold_calibrate.py 8192  --only-new
    python tools/regen/threshold_calibrate.py 16384 --only-new

`--only-new` computes just the gap (it skips cells already present) and
took 100s for 232 cells at n=4096. Then merge into
`python/matchedfilter/threshold.txt` -- the merge is a plain dict update
keyed on (n, snr, f, ratio, fd); nothing in the table depends on its
neighbours, because every cell is an independent bisection.

The CPU side (NOT this thread's work): the CPU has **no hierarchical plan
for bands 64 or 128 at any size**. That gap is why cross-device tests skip
band 128, which is how a wave-reduction bug survived earlier today.

## 3. Cost graph -- HOLD until 1 and 2 land

It selects band 256 when 512 is 2.0x faster on the teaser (0.306 vs 0.156
ms). It cannot be rebuilt honestly over a kernel matrix that is partly
broken and thresholds that are partly refused.

`tools/regen/cost_gpu.py` needs one edit first: it still calls
`set_coarse_margin`, removed when margin was eliminated. With one
calibrated threshold per band there is no margin axis, so `MARGINS`
collapses to `[1.00]` (keep the column so the reader is unchanged) -- four
times fewer cells.

## Where the performance stands

Coarse stage, best-of-7, 512x512 pairs, n=4096, measured as a same-machine
A/B against `136a5e6` (pre-fp16) built in an isolated worktree:

    band    baseline   current   speedup
     128     1.790      0.666     2.69x
     256     1.109      0.848     1.31x
     512     2.264      1.557     1.45x
    1024     4.273      2.871     1.49x

Teaser (16x1024 pairs): GPU hier 0.33 -> 0.27 ms. It dilutes because the
coarse stage is only ~29% of that run -- refine is 56%, fixed overhead 15%.

What paid, in order: one-bin specialisation, SoA switchover, `bit_cast`
staging, twiddle recurrence. **All four DELETE work.** What never paid:
fp16 loads, permuted banks, wide `uint4` loads, deeper tiles, manual
hoisting, dual-bank staging -- all rearrangements.

ISA after the SoA work (band 512, `RADV_DEBUG=asm`): all scalar fp16
ARITHMETIC eliminated (575 ops -> 0); the 294 remaining "scalar fp16" are
`v_mov_b16` (98) and `v_cvt_f32_f16` (196), i.e. data movement and format
conversion, not computation. Largest remaining block is stalls,
`s_delay_alu` 482 + `s_waitcnt` 381 ~ 12%, which neither more waves nor
fewer instructions relieved (both measured).

## Traps that cost time today -- read before starting

  * **Check what was BUILT, not what the script says it builds.** Three
    separate incidents: `compile_one` silently lost its `tile` parameter
    (the resulting NameError did not match a grep for `error[E`); stale
    `_c16t8` artifacts from an experiment sat in `spirv/` and misled two
    rounds; and band 256 ran the old fp32 kernel for the whole session
    because `_COARSE_TILE` selected past the conversion.
  * **Read the compiled code before the fifth guess.** Five source-level
    models were falsified by measurement; both compiled-code reads
    (`RADV_DEBUG=shaderstats`, `RADV_DEBUG=asm` with
    `MESA_SHADER_CACHE_DISABLE=1`) produced root causes immediately.
  * **Timing and correctness in the same breath.** A wave reduction that
    mixed pairs measured 2.27x FASTER while dismissing three quarters of
    the signal. An over-gating threshold measured 0.115 ms against 0.271.
    Both look like wins on a stopwatch.
  * **Run-to-run variance is ~15% at band 128 and ~7% at 512.** Use
    best-of-N, not means; means argued the opposite conclusion twice.
  * **`git add -A` is unsafe here** -- a separate session works the CPU
    path in the same tree. Commit explicit paths.

The full rule set is in `docs/optimization-method.md` (13 rules, each
anchored to something that actually happened).
