# Zen 5 instruction notes (measured, not from documentation)

Measured on AMD Ryzen AI MAX+ 395, one core, `taskset -c 4`, 4.86 GHz assumed for
the ipc figures. **Treat these as a starting point, not truth** — they were taken
on a machine with variable load, the ipc numbers assume a clock that was not
independently verified, and several of them changed once dead-code elimination and
latency-vs-throughput confounds were fixed. Re-measure before relying on any of it.

Reproduce with `/tmp/isurvey.c` and `/tmp/mix2.c` patterns: 8 independent chains
per stream, and **drain every accumulator** or the compiler deletes the loop (this
bit me twice — an early run reported 246983 ipc and another reported 0.0 ns).

## Primitive throughput

| instruction | instr/cyc | effective rate | note |
|---|---|---|---|
| `vfmadd132ps` fp32 FMA | 1.94 | 151 G lane-op/s | baseline |
| `vaddps` fp32 add | 2.05 | 160 G lane-op/s | |
| `vpaddw` int16 add | **3.07** | **478 G lane-op/s** | 1.5x the rate, 2x the lanes |
| `vpaddsw` int16 saturating add | 2.05 | 319 G/s | free clamping, but slower than `vpaddw` |
| `vpmulhrsw` int16 Q15 mul | 2.03 | 316 G mul/s | stays int16, `(a*b+0x4000)>>15` |
| `vpmaddwd` int16 2-way dot | 1.99 | 310 G mul/s | widens to int32 |
| `vpdpwssd` VNNI 2-dot+acc | 1.90 | 295 G mul/s | accumulate is free |
| `vpdpbusd` VNNI int8 4-dot | 1.92 | 596 G mul/s | |
| `vpmaddubsw` int8 2-dot | 2.02 | **629 G mul/s** | saturating |
| `vpmullw` int16 mul low | 1.78 | 277 G mul/s | |
| `vdpbf16ps` bf16 2-dot+acc | 1.37 | 213 G mul/s | dominated by int16 paths |
| `vpmadd52luq` IFMA 52-bit MAC | 1.86 | 72 G mul/s | only 8 lanes — not competitive |
| `vpshrdw` VBMI2 funnel shift | 2.05 | 320 G/s | block-float renormalisation |
| `vpternlogd` 3-input bitop | 2.05 | 160 G/s | fuse sign/mask work |

Not usable for arithmetic: `vpclmulqdq` is carry-*less*, so packed products are
GF(2) not integer; `gfni` is bit permutation.

## Pipe overlap — which instruction pairs co-issue

| pair | alone | mixed | verdict |
|---|---|---|---|
| `vaddps` \| `vpaddw` | 1.81 / 3.07 | **4.09** | disjoint, +33% |
| `vfmaddps` \| `vpaddw` | 2.01 / 3.08 | **3.88** | disjoint, +26% |
| `vmulps` \| `vpaddw` | 1.99 / 3.08 | **3.89** | disjoint, +26% |
| `vaddps` \| `vmulps` | 2.06 / 2.00 | **3.48** | disjoint, +70% |
| `vfmaddps` \| `vpmulhrsw` | 1.97 / 2.05 | 2.05 | **shared port** |
| `vpmulhrsw` \| `vpaddw` | 2.04 / 3.07 | 2.90 | shared |
| `vpmaddwd` \| `vpaddw` | 2.05 / 3.07 | 2.89 | shared |

**The rule that falls out:** integer *multiply* competes with FP *multiply* for the
same pipes, but integer *add* does not — it co-issues with anything FP at +26–33%.
FP add and FP multiply are also on separate pipes (+70%), which is why keeping
`vaddps` and `vmulps` balanced matters more than minimising either.

## What this implies for the transform

A radix-2 butterfly with twiddle is 4 real multiplies + 6 real add/sub.

| representation | cycles/butterfly | vs fp32 |
|---|---|---|
| fp32, split re/im | 0.250 | 1.00x |
| int16 interleaved, `vpmaddwd` | 0.197 | 1.27x |
| **int16 split, `vpmulhrsw`** | **0.1225** | **2.04x** |

`vpmaddwd` looks attractive but widens to int32 and needs shift+pack to get back,
which eats the gain. `vpmulhrsw` stays in int16 end to end and its built-in `>>15`
absorbs one bit of block-float growth per stage for free.

Precision: `vpmulhrsw` costs ~2^-15 relative per multiply; over 20 stages that is
sqrt(20)*2^-15 ~ 1.4e-4. Fine for *screening* (needs ~1e-2), nowhere near enough for
reported values — those still need exact refinement. int8 would give ~1.8e-2, which
is marginal for screening, so int8 is only viable for early stages.

## Memory system (varies enormously with machine load)

| | idle | 28 synthetic hogs | real heavy load (observed) |
|---|---|---|---|
| L1 copy | 266 GB/s | — | — |
| L2 copy | 191 | 22.7 | ~31 |
| L3 copy (8 MiB) | 151 | 3.4 | 2.7 |
| DRAM copy | 40 | 3.3 | 2.6 |
| AVX-512 FMA peak | 324 GF/s | 320 (hogs are memory-bound) | 129 |

L3 is shared and collapses to DRAM speed under load — design for L1/L2 residency.

## Phase 0 result: int16 Q15 transform

A generated, fully-unrolled 32-point codelet, radix [8,4], split re/im, `vpmulhrsw`
twiddles and `vpaddw`/`vpsubw` butterflies, one arithmetic shift per stage to pay
for growth.

| codelet | ns per transform | rel err vs double DFT |
|---|---|---|
| fp32 `fft32_84` [8,4] | 2.191 | exact |
| **int16 `ffti16_32` [8,4]** | **1.609** | 8.5e-04 |

**1.36x on compute, 2x on memory.** Less than the ~2x the raw instruction rates
suggested, because the codelet is not purely arithmetic-bound — the loads, stores and
dependency chains are unchanged in count, only narrower.

Things that turned out not to matter, each measured rather than assumed:
- Removing the per-stage shifts entirely (carrying headroom instead) was **no faster**
  (1.862 vs 1.819 ns) and slightly less accurate. The shifts were not the cost.
- Radix choice mattered more than any of it: [4,4,2] gave 1.78 ns, [8,4] gives 1.61.
  Comparing an int16 [4,4,2] against an fp32 [8,4] understated int16 by a third.

Accuracy budget: 8.5e-04 against a 1e-2 screening requirement is 12x of margin, and
reported peaks are still refined exactly in fp32, so the 1e-5 output budget is
untouched.

Two bugs worth remembering from building this:
- The Stockham index mapping is **DIF** (butterfly first, twiddle the difference).
  Writing a DIT butterfly under it produced a relative error of 1.57 — completely
  wrong, but the impulse test still passed, because an impulse never exercises the
  twiddles. Test with a tone, not an impulse.
- `Re(w*b)` computed as a difference of two rounded products is bounded by
  `|b|*sqrt(2)`, so `a +- w*b` reaches 2.41x the input max. int16 needs headroom for
  that, not just for the nominal 2x of the butterfly.

## What amd-fftw actually does (disassembled)

Extracted from `libfftw3f.a` and counted:
- **Zero integer-SIMD arithmetic.** No `vpmulhrsw`, `vpmaddwd`, `vpdpwssd`,
  `vpdpbusd`, `vdpbf16ps`, `vpaddw`, not even `vcvtps2dq`. The 28 `vpaddd` and 17
  `vpmull` in the whole library are address arithmetic. The low-precision avenue is
  entirely unexploited by them.
- **AoS interleaved complex** with `vfmsubadd`/`vfmaddsub` (2109 uses) plus heavy
  `vpermilps` (2109) and `vmovsldup`/`vmovshdup`. Costed: AoS is 3 instructions per 8
  complex = 0.375/complex; split SoA is 4 per 16 = 0.25/complex. Our SoA layout is
  already the better one and avoids their permute traffic.
- `vaddps` and `vsubps` at 5601 each vs `vmulps` 3043 — **adds are ~55% of their
  arithmetic**, which is exactly where int16's 3x add advantage applies.

## Phase 1a: batch-interleaved layout — rejected on measurement

Tried `x[n*B + b]` so SIMD lanes are the batch index. This removes the four-step corner
turn entirely (no `V_TRANSPOSE` anywhere) and makes the outer twiddle a scalar broadcast
instead of a per-lane vector table. Both are real structural savings. It still loses badly:

| N | B | batched us/xform | single-at-a-time | ratio |
|---|---|---|---|---|
| 2^12 | 16 | 6.38 | 2.21 | 0.35x |
| 2^12 | 64 | 7.01 | 2.39 | 0.34x |
| 2^16 | 32 | 269.97 | 65.21 | 0.24x |
| 2^18 | 64 | 1336.59 | 390.79 | 0.29x |

Correct throughout (rel err 1.4e-07 .. 2.3e-07 vs the single-transform path), so this is
purely a memory-system result. Two causes:

1. **Working set multiplies by W.** The inter-stage buffer goes from N complex to N*W
   complex: 32 KiB -> 512 KiB at 2^12. The single-transform intermediate is L1-resident;
   the batched one is not. Every byte that was L1 traffic becomes L3 traffic.
2. **Stride becomes pathological.** Stage A walks n2 with stride `N1*B*8` bytes — 64 KiB
   at 2^18, so N2=512 reads span 32 MiB with a TLB miss each. The single-transform path
   tiles this into W x W blocks; with lanes already spent on the batch there is no tile
   left to hide the stride in.

Lesson: the corner turn was never the bottleneck, so paying cache residency to delete it
is a bad trade. Batching has to preserve per-transform L1 residency, which means the batch
must be an array of separate contiguous transforms (stride 2N), not an interleave.

## Phase 1b: what batching actually bought

Not the corner turn (see above). Two things:

**1. A detection floor removes the heap-fill phase.** Without a floor the candidate
heap starts empty and every bin pushes until it holds KP = 2K+8 entries; on white
noise that is most of the early scan. Priming from the floor skips it entirely.
Gain (B=16, us/transform):

| N | K=8 | K=64 |
|---|---|---|
| 2^10 | 1.45x | **10.60x** |
| 2^12 | 1.18x | 3.02x |
| 2^14 | 1.04x | 1.55x |
| 2^16 | 1.01x | 1.17x |
| 2^18 | 1.13x | 1.19x |
| 2^20 | 1.00x | 1.05x |

At K=64 the unfloored 2^10 case costs 3.93 us against 0.37 us floored - the search
was costing 10x the transform. With a floor the cost is flat in K.

**2. The floor lets the search fuse into the transform's last stage** (N=1024 path).
The compare happens on registers, so the scan pass and almost all of the output
stores never happen: 0.540 -> 0.381 us. A general-purpose FFT cannot do this because
it must materialise every output.

### Benchmarking note: single-buffer runs overstate large N

Earlier single-transform runs reused one 8 MiB buffer, which is partly L3-resident,
and reported ~400 us at 2^20. Batched over 16 distinct inputs (128 MiB, nothing
cached) the same work costs ~2200 us. The batched figure is the honest one for the
intended use. All four libraries get distinct data in bench_batch, so the comparison
is unaffected - but do not compare a batched number against an old unbatched one.

## Phase 1c: where 2^20 actually goes, and three things that did not help

Ablation at 2^20 (B=16, floor on, us/transform):

| variant | us | reading |
|---|---|---|
| 0 full | 1931 | |
| 6 stage-A load only | **1022** | the load is 53% of everything |
| 2 no element transform | 1982 | element FFT is free, it overlaps |
| 3 no four-step twiddle | 1916 | twiddle is free too |

Same conclusion as at 2^14: the transform arithmetic is not the cost. The load is.

Measured access-shape penalty on this core: sequential read 43.9 GB/s, the same
volume at stage A's 8 KiB stride touching 128 B per row **7.6 GB/s**. Widening the
touched run recovers it - 512 B gives 19.1, 1 KiB 24.7, 2 KiB 30.7.

Three attempts on that, all measured, none kept:

1. **Non-temporal intermediate stores.** Full-line stores whose line is dead until
   stage B reads it back should skip the read-for-ownership. Wash: 2^18 405 vs 407,
   2^20 2200 vs 2184. Code kept behind `APOGEE_NT`, default off.
2. **Huge pages for the big buffers** (`MADV_HUGEPAGE`). No change. The strided walk
   is over the *caller's* input buffer, which we do not allocate. Kept anyway - it
   costs nothing and the TLB argument still holds for the intermediate.
3. **Blocking stage A over G groups per input pass** (`APOGEE_GBLK`). Recorded here
   originally as "gains nothing". **That was wrong** - see the correction below. The
   sequential runs it was judged on had 405-455 us of spread at 2^18, larger than the
   effect, so no conclusion was available either way.

So A=6's 1022 us is 8 MiB of strided DRAM read *plus* 8 MiB of L2 buffer write, and
the two are balanced - which is why trading one for the other does nothing. Getting
past this needs the input read itself to become sequential, not merely wider.

## Tooling for fast iteration

Two things were slowing every experiment down: the full test suite is 40 s, and
run-to-run spread at 2^18 is ~12%, which is larger than most changes worth making.
Comparing two sequential runs cannot see a 5% effect, and several conclusions
earlier in this work were drawn from exactly that kind of comparison.

- `make quick` - 1.75 s correctness gate (unit tests plus a trimmed batch matrix
  that keeps every *mode*: threshold, window, both directions). Run between edits;
  `make test` still runs the full 283k checks before committing.
- `bench/ab A.so B.so` - paired A/B of two library builds, dlopen'd into one
  process and alternated round by round so machine drift hits both equally. It
  checks the two builds return identical peaks before timing anything, reports the
  median per-round ratio and the observed spread, and decides significance itself
  with a two-sided sign test.

Two calibration details that mattered, both found by running the harness against
an identical pair of libraries and demanding it say "noise":

- **R must be even.** The order alternates each round, so an odd R hands one side
  the disadvantageous first slot once more than the other. At R=25 that produced a
  consistent "B slower, p=0.043" between two copies of the same library.
- **p<0.01, not 0.05.** A sweep is six rows; at 0.05 a false call appears roughly
  every third run, which is often enough to believe one.

Usage:

    make libapogee.so && cp libapogee.so /tmp/base.so
    ...edit...
    make ab BASE=/tmp/base.so ABFLAGS="-t 10 12 14 16"


## Correction: group blocking was real, and the first heuristic had it backwards

The three items above were judged on sequential before/after runs whose spread
exceeded the effect. Re-measured with `bench/ab` (paired, drift-cancelled, sign
test, 4 plan-layout trials), holding everything but G fixed inside one build:

| N | old G | best G | effect |
|---|---|---|---|
| 2^12 | 4 | 1 | G=1 **3.8% faster** (38/48) |
| 2^14 | 8 | 1 | G=1 **4.3-5.6% faster** (0/48 for every larger G) |
| 2^15 | 8 | — | within the 3% resolution floor either way |
| 2^16 | 4 | 4 | G=4 3.1% faster than G=1 (32/32); G=16 3.2% *slower* |
| 2^17 | 4 | 4-16 | ~12.5% faster than G=1 (32/32) |
| 2^18 | 2 | 32 | **10.8% faster** (16/16) |
| 2^20 | 1 | 32 | **12.7% faster** (16/16) |

The first heuristic sized G to keep the G group buffers inside L2. That is exactly
backwards: it capped G small at the large sizes, which is the only place a wider
stream helps, and left it large at the small sizes, where it only adds L2 pressure.
What actually decides it is where the *input* lives:

    input <= 256 KiB   G = 1     already cache-resident, wider stream buys nothing
    input <= 1 MiB     G = 4     in L2; a moderate G wins, a large one loses
    input  > 1 MiB     G = 32    out of L2; stream shape is worth a fifth of runtime

Net against the original: 2^12 1.06x, 2^14 1.05x, 2^18 1.11x, 2^20 1.21x, others
unchanged.

**Methodological limit worth remembering:** comparing two *different* builds cannot
resolve a few percent, even with the 3% floor, because their code and buffers are
mapped at different addresses. The cross-build run of this very change reported
"B slower" at 2^12 and 2^15, which the single-build isolation then contradicted.
To tune one parameter, hold the build fixed and vary it with `-e`.

## Binned maximum

`ap_binmax` reports the loudest sample in each bin of the search window, dense and
indexed by bin, with the floor suppressing bins that never cross. Semantically it
is what a matched-filter search wants; the interesting part is what it took to
make it as fast as the top-K path rather than slower.

Four wrong guesses before the measurement, all worth recording:

1. "The heap is the cost." A standalone scan says per-bin max beats a top-K heap
   1.5-2.0x. But the *floor-primed* top-K scan is a compare against a
   loop-invariant threshold plus a branch that is never taken - about 4 ops - while
   a naive per-bin max does four unconditional blends. The heap was never running.
2. "It is the stack frame." Moving the many-bin accumulators out of line: no change.
3. "It is the loop-carried max dependency." Four independent accumulators: no change.
4. "It is the GPR->vector broadcast of k0." Carrying it as a vector counter:
   0.642 -> 0.592, real but small.

What actually mattered:

- **Prime the running maximum with the detection floor.** A bin never reports below
  it, so starting there is exact, and it turns the four blends into a branch that
  is almost never taken. Same trick as the top-K path, which is why that path had
  been winning.
- **Keep the accumulators in registers when there is one bin.** Indexed by a runtime
  bin number they live in memory and every surviving block is a four-vector
  load-modify-store. A register fast path for nb==1 is worth ~1.25x at 2^12-2^16.

Two measurement traps hit along the way, both already in this file and both hit
anyway: a stale statically-linked benchmark reported 0.60x when the rebuilt one
says 0.99x, and the two kernels take the threshold in different units (squared vs
not), so an early head-to-head gave them wildly different selectivity and claimed
a 1.9x that was not real.

Result, us/transform at B=16 with the floor on, single bin over the window:

| N | top-K | binmax | |
|---|---|---|---|
| 2^10 | 0.361 | 0.366 | 0.99x |
| 2^12 | 2.442 | 2.343 | 1.04x |
| 2^14 | 10.050 | 10.269 | 0.98x |
| 2^16 | 51.493 | 50.773 | 1.01x |
| 2^18 | 352.6 | 302.4 | **1.17x** |
| 2^20 | 1832 | 1650 | **1.11x** |

Many bins costs more than one bin - 16 bins at 2^10 is 0.67 against 0.37 - which is
expected, since the accumulators leave registers and there are 16 outputs instead
of one.

## Two more measured negatives at 2^12-2^14

Chasing the small-size gap, the ablation says stage A's *body* is 1.39 us of 2.30
at 2^12, of which the codelets are only 0.41. Splitting that further:

| ablation | 2^12 | 2^14 |
|---|---|---|
| full | 2.297 | 10.293 |
| no corner turn | 2.350 | 9.955 |
| no stage-A body | 1.225 | 5.197 |
| **no intermediate store** | **2.006** | **8.273** |

So the intermediate store is 13% at 2^12 and 20% at 2^14. Two hypotheses, both wrong:

1. **Runtime N1/N2 indirection.** kernel1024.c is fully unrolled with compile-time
   sizes and spends 47% outside its codelets; the generic path spends 67% at the
   same codelet cost. Compiling balanced.c with N1/N2 as literals: 3-5%. Not it.
2. **L1 set aliasing on the intermediate row stride.** N2 is a power of two, so a
   tile column's AP_W stores land on sets a power of two apart - exactly what made
   the element stride 33 instead of 32. Padding the row by one vector, isolated on
   a single build with `-e`: noise at every size.

The store costs what it costs: 128 KiB at 2^14 at ~63 GB/s is L2 write bandwidth.
It is inherent to materialising the intermediate, and the only way past it is to
make fewer passes over the data - which is the structural difference with FFTW,
not a tuning knob.

## Packed-instruction throughput, and a correction

Definitive table, 512-bit, 12 independent chains, every accumulator drained:

| instruction | instr/cyc | useful G MAC/s | vs fp32 FMA |
|---|---|---|---|
| `vfmadd ps` (16 fp32) | 2.04 | 153.3 | 1.00x |
| `vpdpwssd` (VNNI i16) | 1.53 | 230.1 | 1.50x |
| `vpdpbusd` (VNNI i8) | 1.53 | 460.2 | 3.00x |
| `vdpbf16ps` (bf16) | 1.90 | 286.2 | 1.87x |
| **`vpmaddwd`** (i16->i32) | **2.04** | **307.1** | **2.00x** |
| `vpmulhrsw` (Q15 i16) | 2.05 | 307.6 | 2.01x |
| **`vpaddw`** (i16 add) | **2.72** | **408.4** | **2.67x** |
| `vaddps` (16 fp32 add) | 2.04 | 153.7 | 1.00x |

VNNI is the wrong instruction here: it issues at 1.53/cyc, giving back most of its
2-MACs-per-lane advantage. The plain int16 ops are at full issue rate, and since
butterflies are ~69% adds the available arithmetic speedup is ~2.2x.

**Correction to the earlier "int16 is only 1.19x" note.** That measurement called
`clock_gettime` twice around a ~150 ns region, and the timer is ~25 ns a side - a
third of what was being measured. Amortising the timer over 40 calls:

| | ns/call | per 1024-pt transform | |
|---|---|---|---|
| fp32 `fft32_84` | 38.32 | 0.1533 us | - |
| int16 `ffti16_32` | 49.57 | 0.0991 us | 1.55x |
| int16 `ffti16_32_ns` | 46.82 | 0.0936 us | **1.64x** |

So int16 is worth 1.55x as it stood and 1.64x with the per-level shifts removed -
not 1.19x. The conclusion drawn from that number ("reduced precision cannot pay
for the refinement it forces") was wrong.

The shifts were 320 of 1162 instructions, 28%, and exist only to stop `|a +- b|`
overflowing. Replacing them with headroom in the input scale gives 0.90
instr/point against fp32's 1.50. Measured accuracy of the no-shift 32-point
codelet, worst case over all outputs:

| headroom | rel err vs peak |
|---|---|
| 3 bits | 1.9 (overflows, as the 2^levels bound says it must) |
| 4 bits | 3.5e-04 |
| 5 bits | 4.9e-04 |
| 6 bits | 9.7e-04 (less input precision) |

5 bits is the safe choice for a 5-level codelet. That is screening accuracy: rank
with it, then compute the winning bin's value exactly.

**New measurement trap:** never time a region shorter than ~1 us with a
clock_gettime on each side. Amortise over enough calls that the timer is <1% of
the region, or the result is dominated by measurement overhead - it cost a 1.64x
here and was read as 1.19x for several rounds of reasoning.

## int16 screening pipeline: prototype results

Built a standalone prototype of the int16 screening transform at N=1024 with
lanes = batch (32 int16 lanes = 32 transforms), which removes the four-step corner
turn: the lane index *is* the transform index, so both stages are plain
element-space transforms and the four-step twiddle becomes a scalar broadcast.

| piece | us/transform |
|---|---|
| codelets alone (2 x ffti16_32_ns) | 0.0936 |
| both stages integrated, contiguous layout | **0.1522** |
| same with the twiddle+renormalise removed (wrong results) | 0.1625 |
| fp32 codelets alone, for reference | 0.1533 |
| quantise + interleave, **scalar** | 3.93 |

Three things this establishes:

1. **The integrated int16 transform is 0.152 us/transform** against the fp32 path's
   integrated ~0.29 (0.36 total binmax minus deint and scan). So the arithmetic
   route works - roughly 1.9x on the transform itself.
2. **But it does not reach the 0.094 the codelets promise.** The inter-stage
   load/store costs 0.058, and removing the twiddle makes it *slower*, so the loop
   is throughput-bound rather than paying for any one piece. Same pattern as every
   other size in this project.
3. **The corner turn has not gone away - it moved into the quantise pass.** Writing
   batch-major int16 from per-transform fp32 input is a 32x32 int16 transpose. The
   scalar version costs 3.93 us/transform and is the whole ballgame.

Projected total at 2^10 with a vectorised quantise (32x32 int16 transpose via
vpermt2w, ~160 instr per 2 KiB block, ~0.05 us/transform):

    quantise 0.05 + transform 0.152 + scan 0.03 + refine 0.02 = 0.25 us

against amd-fftw's 0.26. **A tie, not the 1.25x projected earlier** - because the
integrated transform is 0.152, not the 0.094 the isolated codelets suggested.

The one way it becomes a clear win is if the caller supplies input already
quantised (the ap_qinput API exists for exactly this): 0.152 + 0.03 + 0.02 = 0.20
against 0.26, about 1.3x. That is a real option for a pipeline whose data is
already fixed point, but it is not a like-for-like comparison with a library that
must take fp32.

## Stage-B blocking: no gain

Stage A's input walk touches 128 bytes per 8 KiB row, and widening it with group
blocking was worth 1.05-1.21x. Stage B reads the intermediate with the same shape
- AP_W floats out of every `istr` row, 64 bytes per 4 KiB at 2^20 - so the same
treatment looked obviously right.

It is not: blocking 4, 8 or 16 column blocks per pass measures 1.02-1.05x *worse*
at 2^18 and 2^20, and neutral at 2^16 (paired A/B, same build, only the knob
varying). The difference from stage A is that stage B's stride is constant and
short enough for the hardware prefetcher, and the wider buffers cost L2 for
nothing. Default 1; mechanism kept behind `APOGEE_BBLK`.

Ablation of the large sizes with the current build, windowed binmax, B=16:

| | 2^14 | 2^16 | 2^18 | 2^20 |
|---|---|---|---|---|
| full | 10.43 | 52.39 | 311.73 | 1957.85 |
| no stage-A body | 5.46 | 25.55 | 175.54 | 1013.37 |
| no element FFT | 10.96 | 54.15 | 301.15 | 1773.38 |
| no corner turn | 10.74 | 51.79 | 301.37 | 1691.21 |

At 2^20 the corner turn is 14% and the element FFT only 9%; at 2^14 removing
either is *slower*. Effective bandwidth at 2^20 is 24.6 MiB per transform in
1958 us = 12.6 GB/s against 43.9 sequential, so the headroom is real but it is
not in any single pass.
