# CPU work: state and next steps

Written as a handoff. Everything here is measured or read from the code;
where something is a design rather than a result it says so.

## State

`main` is green: 427 passed, 3 skipped, 0 failed, GPU included. The GPU
failures recorded here earlier were the other agent's uncommitted `.spv`
files mid-rebuild and have since landed. A transient `test_spirv.py`
failure during a run means that rebuild is in flight again -- do not "fix"
it and do not `git checkout` those paths.

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

## CPU bands 64 and 128: DONE

Implemented as designed below, plus two things the design did not foresee.

    coverage of the (n, band) sweep   CPU 14 -> 24 of 24 cells
    pytest                            427 passed, 3 skipped
    ISAs                              294 passed under AVX3, AVX2 and SSE4

### What landed

  * `pairbatch_size()` / `create_small()` in balanced-inl.h: a plan for
    N <= 128 carrying only the element buffers, the element twiddles and the
    bin accumulators. No four-step, no corner turn, no intermediate -- with
    lanes across PAIRS the whole N-point transform is one element transform.
  * `binmax_prod_batch` runs AP_W pairs per call; `small_scan` keeps one
    running maximum per lane. Every lane shares the output index k, so the
    scan is a plain walk over the window.
  * `pairbatch`/`binmax_prod_batch` on the back-end struct, `split()` and
    `has_prod()` returning 0 for these plans so the matched filter does not
    store spectra group-major for a split that does not exist.
  * matchfilt.c stores the template bank `[group][element][lane]` when the
    plan asks, pads it to a multiple of AP_W with zeros, and broadcasts the
    data spectrum into `[element][lane]` once per segment. A scattered
    `tsel` gathers into a staging pair instead.
  * `fft()`, `binmax()` and `binmax_split()` on a small plan reuse the pair
    kernel with the input broadcast to every lane. They are setup-path calls
    at these sizes; a second kernel would be a second correctness surface.

### The bug underneath it

`fft8_prod` wrote its result into the SCRATCH buffer pair and said so in its
return value. Every caller of `codelet_prod` ignores that return value, so
an 8-point product codelet was silently wrong -- and nothing had asked for
one, because `efft_prod` only fuses single-level element transforms and 8
never arose as one. Band 128 factors 16x8, asked for it, and came back as
noise at 1e34.

Fixed in gen.py, where the other single-pass codelets already avoid it: a
codelet that does not READ `ar` can write its result there and keep the
ping-pong parity even, and the `prod` case was missing from that condition.
Regenerating changes 9 lines, all inside fft8_prod; everything else is
byte-identical. `codelet_prod` now states the contract.

### The opportunity it exposed -- NEXT ITEM

The pair-batched path is faster than the balanced split at the sizes the
balanced split CAN do. Interleaved in one build (MF_PBMAX moves the cutoff),
nd=8 nt=64:

    N= 256   213.1 -> 86.5 us   2.16x
    N= 512   583.8 -> 313.4 us  1.97x
    N=1024   626.6 -> 381.4 us  1.61x    8 of 8 rounds at every size

Larger than everything else measured on the CPU this session. It is NOT the
default because lanes are pairs and a batch below AP_W pads:

    N= 256  nd=1 nt=1  0.52x       N=1024  nd=1 nt=1  0.19x
    N= 256  nd=8 nt=16 1.66x       N=1024  nd=8 nt=16 1.38x

Crossover around nd*nt ~ 24. Raising the cutoff needs a policy on batch
shape, and probably lanes that flatten (d, t) instead of spanning templates
within one d, so a one-template batch can fill them from the data side.
Shipping the cutoff at 128 on the strength of wide-batch numbers alone would
be a fitted bound.

### The design, as it was written and as it held

Process AP_W PAIRS per call with lanes across pairs, so there are no stages
and no corner turn.

  1. `efft_prod` already does product + transform for AP_W independent
     lanes, and for M2==1 calls `codelet_prod(M, ..., 1, AP_W)` -- S=1,
     DS=AP_W -- which already expects `[freq][pair]`. Held exactly, for
     band 64. Band 128 takes the M2!=1 branch, which had never run, which
     is where fft8_prod was waiting.
  2. **Transpose at INGEST, not in the loop.** Held: the template bank is
     transposed in `ap_mf_set_template`, and the data side needs no
     transpose at all because it is the same in every lane.
  3. **One function replaces the pipeline.** Held: stageA_prod_gm, stageB
     and binmax_one collapse into efft_prod + small_scan.
  4. Plan plumbing. Held, plus two back-end entry points the design did not
     account for.

### Rejected fallback -- still rejected, now with a number

Accepting band < 256 and internally using 256. It would have given no
speedup and a different coarse statistic from the GPU's. Measured, band 128
costs 0.067 us/pair against band 256's 0.351: a factor of 5.2 that the
fallback would have thrown away.

## Also outstanding

  * **Raise the pair-batch cutoff above 128** -- see above. The biggest
    single CPU number measured so far, blocked on batch-shape policy.
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
