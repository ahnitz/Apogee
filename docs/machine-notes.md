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
   2^20 2200 vs 2184. Code kept behind `PEAKFFT_NT`, default off.
2. **Huge pages for the big buffers** (`MADV_HUGEPAGE`). No change. The strided walk
   is over the *caller's* input buffer, which we do not allocate. Kept anyway - it
   costs nothing and the TLB argument still holds for the intermediate.
3. **Blocking stage A over G groups per input pass** (`PEAKFFT_GBLK`). Widens the
   touched run to G*128 B at no extra total bytes. Gains nothing: G group buffers
   need G*N2*PF_W*16 bytes, so G=4 at 2^20 is 1 MiB and evicts L2 exactly as fast as
   the wider stream helps. G=1 405/2120, G=2 408/2118, G=4 406/2162 against 405-455
   of run-to-run noise. Kept at a conservative G because it is never worse and helps
   the mid sizes slightly.

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

    make libpeakfft.so && cp libpeakfft.so /tmp/base.so
    ...edit...
    make ab BASE=/tmp/base.so ABFLAGS="-t 10 12 14 16"
