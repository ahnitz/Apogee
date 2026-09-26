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

### Pair batching at 256–1024: adaptive dispatch

Automatic dispatch now opts in on measured AVX3, AVX2 and SSE4 targets for
actual calls with at least 8 data segments and 16 contiguous templates,
aligned template start, at least 75% SIMD lane occupancy, and a single bin
covering at least half the transform. Other calls retain the balanced path.
The total D×T is insufficient: lanes span templates, and 32×1 pads badly.
One-data calls also regressed when ingestion was included, despite wins in
kernel-only timing, so they deliberately retain the balanced path.

A second packed layout is allocated lazily on the first eligible call.
Only initialized requested rows are copied; later setters update both layouts.
This adds memory and first-call setup cost, and alternating wide and narrow
calls retains the second layout. Allocation failure falls back to balanced.
`MF_PBMAX=128` forces balanced at these sizes, and `MF_PBMAX=1024` forces
pair batching; neither environment override is changed internally.

Interleaved measurement on Ryzen AI Max+ 395, AVX3, 8×64, seven rounds:

| N | Steady-state speedup | Including data and template ingestion |
|---|---:|---:|
| 256 | 2.31× | 1.81× |
| 512 | 1.90× | 1.48× |
| 1024 | 1.83× | 1.37× |

Every round won at these shapes. These are matched-filter batch timings,
not a claim of equivalent end-to-end PyCBC speedup. Reproduce with
`python tools/bench_pairbatch.py` and `--include-ingest`; use `MF_ISA=AVX2`
or `MF_ISA=SSE4` for narrower targets. ARM retains its original dispatch
until measured there. Regression tests exercise updates, subsets, padding,
windows, counts, and hierarchical series against forced balanced execution.

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

## The overnight investigation, 2026-09-26

Eleven cycles of measure-commit-review so far, of twenty. One change
shipped; the rest is diagnosis, and three of the commits retract earlier
ones of mine.

### Shipped

**Split-radix product codelets** (72ec6c4). The Stockham `fft*_prod`
codelets bounce through a scratch buffer between their two passes, indexed
at the OUTPUT stride so successive calls walk the whole element buffer. The
split-radix codelets do the whole DAG in registers -- they carry
`(void)br;(void)bi;` -- and gen.py had no product variant. Adding one
deletes the traffic rather than blocking it better. Paired and interleaved:

    AVX-512  band 256 1.044-1.164   band 512 1.137   band 1024 1.073
    AVX2     band 256 1.103          band 512 1.100   band 1024 unchanged
    SSE4     band 256 1.053          band 512 1.072   band 1024 unchanged
    flat n=4096 1.054 (5 of 5); n=16384 and 65536 unchanged, and those are
    controls -- eprod_ok is false there so codelet_prod is never called.

Band 1024 is "unchanged" on the narrow targets by design, not by omission:
m=32 is where it lands and m=32 is gated to AP_W >= 16.

m=32 and m=64 gated to AP_W >= 16: ungated, m=32 measured 1.075x on
AVX-512 but 0.991x on AVX2 with the new side swinging 292-332us against a
steady 305-308. n=128 is a built-in control (it uses neither changed
codelet) and measures 1.00.

### The threshold table is keyed on the wrong thing

Chasing why bands 64/128 cannot be selected ended somewhere unexpected. The
blocker was recorded as a performance regression; it is a correctness one --
band 128 dismisses 2.9e-2 of INJECTED SIGNALS against a 1e-3 budget.

The cause is the table's key, `(n, f, ratio, snr, fd)`, which omits band on
the argument that samples-across-the-peak is `band/B_eff` with no band left
in it. At a fixed (f=0.70, ratio=1.20) the safe threshold runs 2.8078,
2.9797, 3.1000, 3.2719 across bands 128/256/512/1024 -- **16.5% on the band
axis alone**. It is the coarse maximum: a max over `band` lags grows like
sqrt(2 ln band), and sqrt(ln band) predicts the other three points within
2.7%.

The full grid (`tools/threshold-by-band-4096-experimental.txt`, 59 rows)
shows the spread is ordered by f -- 19.9% at f=0.60 down to 3.1% at
f=0.995 -- because as f approaches 1 the signal dominates the noise floor.
**That is why both shipped tables could omit band and look correct.**
threshold.txt is measured at one band per n. accuracy.txt justifies the
same omission with a 1.14x spread measured, its own header's words, "across
band/B_eff from 16 to 128" -- every cell at ratio >= 16, where band does
not matter. Real references run at ratio 1.3-5.3. Both validated the
omission outside the operating range, so the third key is two tables.

Applying a sqrt(ln band) correction at lookup INSTEAD was measured and
rejected: 2.13x slower at band 256, 1.88x at 512, to fix a 4% margin that
dismisses 0 of 523 injections. A gate is nonlinear in its threshold and
few-percent accuracy is not enough to apply to one.

### `fd` is a promise about signals, not about trigger lists

Marginal NOISE triggers are dismissed at 2.4e-2 (captured) to 3.7e-1
(synthetic) while injections are dismissed at 0 of 2400. Not a defect: a
signal's in-band fraction is fixed by the template, a noise fluctuation's
is an independent draw. At f=1.0 nothing is dismissed at all, which is the
mechanism check. It matters anyway -- a background estimated from the
trigger distribution is not filtering signals.

### A bank that does not match its reference spends headroom

`src/hmf.c` refresh_template(): `f = p->ref_on ? p->ref_f : p->fpow[t]`.
The per-template fraction is computed and used only when no reference is
set. Loss is monotone in the template's own f: 0 above 0.936, 48.3% at
0.739. The captured pycbc bank sits FURTHER from its reference and loses
nothing, because it runs at band 1024/ratio 5.33 where the threshold audits
2.5% BELOW safe rather than 4.1% above.

### Everything left is about 1.2x

    corner turn        1.16x   structural to the four-step; the pair-batched
                               path avoids it and its buffers are 2 MiB at
                               n=16384 against a 1 MiB L2
    plain int16        1.15x   precision is FREE (0.01% against 4.1% of
                               headroom, 400x); throughput is the question
    int8 reject pass   1.19x at band 512, 1.31x at 1024, 0.99x at 256

Phase 3's "unsafe flips stay at zero by construction" is a fit to 520 pairs
and every wider sample breaks it, including the captured data (worst
0.96387 against a 1.0166 bias). A safe bias rejects less, so its 6.2% pass
rate is really 17.9-52.7%.

### Tools left behind

    tools/audit_threshold.py --coverage   table grids vs the operating range
    tools/audit_threshold.py --repeat N   the noise floor (sd 1.0-1.3%)
    tools/regen/threshold_lowratio.py     per-band rows, resumable
    AP_NOXPOSE=1 build                    ablate the corner turn
    tests/_gatelib.py                     one gate measurement, per template

### Traps hit, in case they recur

  * An ablation gated on a plan field measures its own branch. The ablated
    build came out SLOWER than the real one. Make it compile-time.
  * A cost measurement on data with a signal in every block reads 90-100%
    escalation and says nothing. Use pure noise.
  * Never compare threshold rows across band; it cost a whole wrong
    diagnosis (a070137, retracted in 6a9878e).
  * Quote no spread without the noise floor.
  * cwd-relative `sys.path.insert` -- hit three times.

## Also outstanding

  * **SWAR** -- the CPU equivalent of fp16 for the coarse stage. Queued
    deliberately behind the structural work.
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
