# The portable back end

`balanced.c` is compiled a third time with `AP_PORTABLE`, which swaps the x86
intrinsics in `simd.h` for GCC/Clang vector extensions (`src/simd_portable.h`).
The same source then builds anywhere those compilers do, including macOS and
arm64, with no second set of kernels.

It is built on x86 as well, so both back ends live in one binary and can be
compared inside a single process. `MF_ISA=portable` selects it; on non-x86 it
is the only one there is.

**Status: not yet at parity.** The bar is no measurable loss against the AVX2
intrinsics at the same width. The transform meets that; the peak scan does not.

## Where it stands

Paired A/B, alternating rounds, one Zen 5 core, both back ends 8-lane so
AVX-512 cannot enter either side. Ratio is portable/AVX2, lower is better.

| n | shape | AVX2 | portable | ratio |
|---:|---|---:|---:|---:|
| 1024 | 4x16 | 0.060 ms | 0.087 ms | 1.54x |
| 4096 | 4x16 | 0.219 ms | 0.301 ms | 1.39x |
| 16384 | 4x16 | 1.013 ms | 1.357 ms | 1.34x |
| 65536 | 2x8 | 1.142 ms | 1.511 ms | 1.32x |
| 262144 | 1x4 | 1.516 ms | 1.850 ms | 1.20x |

Split by phase at n=16384, timed through the back-end struct directly:

| phase | ratio |
|---|---:|
| forward transform | 1.02x |
| product + binned max | 1.36x |

The transform is at parity. Everything left is in the peak scan.

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

## What is left: the peak scan

The scan's inner loop compares a magnitude vector against the running maximum
and, when some lane improves, blends four vectors:

```c
unsigned g = V_GT_MASK(m2, am);
if (g) { am = V_BLENDM(g, am, m2); ... }
```

`V_GT_MASK` returns a *bitmask*. On AVX-512 that is a native `__mmask16` and
free; on AVX2 it is one `vmovmskps`. Portably there is no movemask, so the
current implementation extracts each lane to a bit, and `V_BLENDM` then expands
those bits back into a lane mask -- the round trip is paid twice per iteration
and is the whole remaining 1.36x.

The fix is to stop round-tripping through a bitmask: carry an opaque vector
mask type (`__mmask16` on AVX-512, `__m256` on AVX2, an integer vector
portably) with `V_CMP_GT` / `V_SEL`, and only materialise bits where a bitmask
is genuinely wanted. That removes work from the AVX-512 path too.

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
