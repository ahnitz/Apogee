# The portable back end

`balanced.c` is compiled a third time with `AP_PORTABLE`, which swaps the x86
intrinsics in `simd.h` for GCC/Clang vector extensions (`src/simd_portable.h`).
The same source then builds anywhere those compilers do, including macOS and
arm64, with no second set of kernels.

It is built on x86 as well, so both back ends live in one binary and can be
compared inside a single process. `MF_ISA=portable` selects it; on non-x86 it
is the only one there is.

**Status: close, not yet at parity.** The bar is no measurable loss against the
AVX2 intrinsics at the same width. The remaining gap is 7-16% and is diffuse:
both phases now sit near 1.1x rather than one of them carrying it.

## Where it stands

Paired A/B, alternating rounds, one Zen 5 core, both back ends 8-lane so
AVX-512 cannot enter either side. Ratio is portable/AVX2, lower is better.

| n | shape | AVX2 | portable | ratio |
|---:|---|---:|---:|---:|
| 1024 | 4x16 | 0.056 ms | 0.064 ms | 1.16x |
| 4096 | 4x16 | 0.215 ms | 0.250 ms | 1.16x |
| 16384 | 4x16 | 1.013 ms | 1.151 ms | 1.13x |
| 65536 | 2x8 | 1.157 ms | 1.320 ms | 1.16x |
| 262144 | 1x4 | 1.542 ms | 1.664 ms | 1.07x |

Split by phase, timed through the back-end struct directly:

| n | transform | product + binned max |
|---:|---:|---:|
| 4096 | 1.12x | 1.10x |
| 16384 | 1.11x | 1.17x |
| 65536 | 1.05x | 1.11x |

Two changes got it here, in order of size: disabling GCC's SLP pass (2.3x ->
1.1x on the transform) and removing the bitmask round trip from the peak scan
(1.36x -> 1.10x).

## GCC's SLP vectoriser costs 2.3x

The first working version ran 2.30x slower than the intrinsics on the
transform. It executed **the same number of instructions** (22200 against
22300), with the same FMA count and the same ymm usage, on an identical plan
split. Same work, same instruction mix, 2.3x the time.

The cause is `-ftree-slp-vectorize`. The code is already explicitly vectorised;
the SLP pass re-splits and recombines those vectors, and the result schedules
far worse. Disabling that one pass:

| build | transform | scan |
|---|---:|---:|
| -O3 | 2.30x | 2.66x |
| -O3 -fno-tree-slp-vectorize | 1.09x | 1.35x |
| -O3 -fno-tree-slp-vectorize -fno-unswitch-loops | **1.02x** | 1.36x |
| -O2 | 1.09x | 1.15x |

`-O2` avoids it too, by giving up everything else `-O3` does. `setup.py` probes
the two flags and applies them only to the portable objects, and only if the
compiler accepts them -- dropping them silently would restore the 2.3x.

Not reproduced on Clang, which is the compiler that matters for macOS. That
needs measuring on a Mac rather than assuming.

## The bitmask round trip, and its removal

The scan's inner loop compared a magnitude vector against the running maximum
and, when some lane improved, blended four vectors through a *bitmask*:

```c
unsigned g = V_GT_MASK(m2, am);          /* lanes -> bits  */
if (g) { am = V_BLENDM(g, am, m2); ... } /* bits -> lanes, four times */
```

On AVX-512 the bitmask is a native `__mmask16` and free; on AVX2 it is one
`vmovmskps`. Portably there is no movemask at all, so the bits were extracted
lane by lane and then expanded back for every blend -- paid twice per
iteration, and worth 1.36x on its own.

The mask type is now opaque: `vm` is `__mmask16` on AVX-512, `__m256` on AVX2
and an integer vector portably, with `V_CMP_GT`, `V_SEL` and `V_MASK_ANY`.
Bits are materialised only where bits are genuinely wanted (the window mask).
`V_GT_MASK`, `V_BLENDM` and `VI_BLENDM` had no remaining users and are gone.

The AVX-512 and AVX2 paths are unchanged in measurement and still agree with
numpy exactly.

## What is left

7-16%, spread evenly across both phases rather than concentrated anywhere.
Nothing in the profile points at a single construct now, so closing it means
either finding another pessimising pass or accepting the gap and saying so.
Clang has not been measured at all yet, and macOS is a Clang target.

## Things that were not the problem

Worth recording, because each looked obvious and cost a measurement:

- **Element-wise vector writes.** The first `v_transpose`, `v_deint` and
  `v_inter` assigned lane by lane, compiling to 500 `vinsertps`. Replacing them
  with `__builtin_shufflevector` networks cut that to 38 -- and changed the
  runtime not at all. The scalar inserts were real and were not the bottleneck.
- **Missing FMA contraction.** The FMAs were being generated; the counts are
  within 15% of the intrinsic build.
- **A different algorithm.** Both back ends report the same `has_prod` and the
  same N1 x N2 split at every size.

## A latent bug this found

`ap_lane_width()` read `return (b == &ap_be_bal8) ? 8 : 16;` -- it identified
back ends by pointer and defaulted to 16. The portable back end is 8-lane, so
it was told it had 16, and the matched filter stored every spectrum group-major
for the wrong width. The transforms still agreed to 1e-8; only the correlation
came out wrong, on a delta input that should have been exact. Any future
back end has to be added there explicitly.
