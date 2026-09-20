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
