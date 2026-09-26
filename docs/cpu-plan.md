# CPU work: state and next steps

Written as a handoff. Everything here is measured or read from the code;
where something is a design rather than a result it says so.

## State

`main` is green on the CPU surface: 293 passed, 3 skipped, 0 failed
(`pytest -k "not gpu"`). The full suite also shows 2 GPU failures that are
NOT from this work -- they come from the other agent's 18 uncommitted
`.spv` files mid-rebuild. Do not "fix" them and do not `git checkout` those
paths; that would destroy in-flight work.

**Coordination hazard.** Two agents share this working tree. `git add -A`
cross-contaminates commits -- one of my changes already landed under an
unrelated commit message that way. Commit explicit paths.

## Shipped this session (CPU)

Cumulative, interleaved old/new so drift cancels:

    coarse band  512   1.455 -> 1.205 ms   1.218x   6 of 7 pairs
    coarse band 1024   2.728 -> 2.568 ms   1.063x   7 of 7
    coarse band 2048   5.941 -> 5.247 ms   1.132x   7 of 7
    flat  n=4096       0.699 -> 0.639 ms   1.094x   6 of 6

  * **N1xN2 split tuned for the coarse sizes.** create() had only ever
    tuned 2^12 and 2^18 (the FLAT filter's sizes); 2^8..2^11 took the
    balanced default. Now 16x32 at 2^9 and 128x16 at 2^11.
  * **p->ilay enabled.** The contiguous intermediate layout was implemented
    in both stages with a correctly-sized buffer and nothing ever assigned
    the field, so the strided path was the only one that had ever run.
  * **MF_HMF_TRACE hoisted** out of the per-pair loop (getenv was 1 of 26
    samples).

Verified across ISAs: 424 passed under MF_ISA=AVX3, AVX2, SSE4. The 2^11
split helps every ISA; 2^9 is an AVX-512 effect that costs others nothing.

## THE outstanding item: CPU bands 64 and 128

### Why they are missing

The CPU transform is a balanced two-stage split. Stage A lays AP_W lanes
across n1, stage B across n2, so both factors need a full vector:

    N >= AP_W^2     AVX3 (16) -> 256   AVX2 (8) -> 64   SSE4/NEON (4) -> 16

On AVX-512 band 128 is therefore STRUCTURAL: it splits only as 16x8 and 8
is half a vector. On the narrower targets it is POLICY -- supported()
hard-codes `N<256u` (balanced-inl.h:85) so the accepted set cannot depend
on the host.

### The design (validated against the code, not implemented)

Process AP_W PAIRS per call with lanes across pairs, so there are no stages
and no corner turn.

  1. `efft_prod(band, dr,di,tr,ti, X,Xi,S,Si, itwr,itwi)` already does
     product + transform for AP_W independent lanes. For M2==1 it calls
     `codelet_prod(M, ..., 1, AP_W)` -- S=1, DS=AP_W -- which ALREADY
     expects `[freq][pair]` with AP_W pairs contiguous. That is the layout
     this path produces, so the transform half needs no new kernel.
     `efactor(64)` gives M2=1 (single codelet, no twiddles);
     `efactor(128)` gives 16x8 with twiddles the plan already builds.
     `esupported()` covers both.
  2. **Transpose at INGEST, not in the loop.** p->dre/dim/tre/tim are
     [row][n]. Gathering at stride n per element would cost more loads than
     the path saves. Store a transposed copy of the coarse band when the
     spectra are set -- once per upload, amortised over every pair that
     references it. This is the same argument that made the GPU's packed
     coarse banks worth keeping.
  3. **One function replaces the pipeline.** With lanes = pairs,
     stageA_prod_gm, stageB and binmax_one collapse into: form the
     transposed product, efft_prod, then |v|^2 and a max per lane. The
     window is a mask over k; nb is 1 on the coarse gate by construction.
  4. Plan plumbing for the band-sized element buffers and twiddles, and a
     branch in create()/supported() for N < AP_W^2.

Roughly 200 lines across balanced-inl.h, hmf.c and the plan struct. It must
land in one piece -- a half-converted path is worse than either endpoint.

### Rejected fallback

Accepting band < 256 and internally using 256. It makes the API work but
gives no speedup, which defeats the point of a small band, AND produces a
different coarse statistic from the GPU's -- so it would not even fix the
cross-device testing motivation.

### Testing is already unblocked

`test_hierarchical_matches_flat_on_the_same_device` compares hierarchical
against the FLAT filter on the same device, needing no CPU plan or table.
It covers band 128 on the GPU and is verified to FAIL on the wave-reduction
bug. The gap is a missing capability now, not a blind spot.

## Also outstanding

  * **SWAR** -- the CPU equivalent of fp16 for the coarse stage. Queued
    deliberately behind the structural work.
  * **A 2D-tile diagram** for the docs, to show what the tiling actually
    does.
  * **stageA_prod_gm is still 46%** of the coarse stage (was 58%). What
    remains inside it is two 16x16 transposes per block and a rolled
    t-loop. The coarse stage sits ~2.2x off single-core FMA peak, down from
    ~2.6x, and the rest is spread rather than concentrated.

## Negatives -- measured, do not retry

  * GMAJOR=0: 0.665 and 0.744 of the default at bands 512 and 2048.
  * GBLK=4/8, BBLK=2: within noise at coarse sizes.
  * MF_NOSTORE: no effect; the coarse plan has no series buffer.
  * Hoisting plan fields out of stageA_tail to defeat aliasing: BYTE-
    IDENTICAL output. Strict aliasing already lets GCC prove a float store
    cannot touch an int struct member.
  * Dropping binmax_one's unused arr/aii/axx accumulators: they sit inside
    `__builtin_expect(..., 0)` and almost never execute.

## Method notes that cost real time to learn

  * **This box drifts ~18% between runs minutes apart.** Sequential A/B
    measures thermal state as if it were code. Interleave old,new,old,new
    and report the paired ratio. An all-old-then-all-new sweep first put
    the 2^9 split at 11.8% when the honest figure is 5.4%.
  * **Check the symbol is on the hot path before disassembling it.** The
    first CPU instruction mix I took was of `fft64_prod`, which has ZERO
    call sites. Sample with gdb (`bt 1` in a loop) instead of guessing.
  * **Static disassembly of a function with runtime branches measures both
    paths.** stageA_prod_gm reads 1245 instructions before and after the
    ilay change because both store paths are compiled in.
