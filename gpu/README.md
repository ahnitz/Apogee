# GPU spike

Phase 1 of `docs/plans/gpu.md`: find out whether fusing the correlation and
the peak scan into one kernel is worth a bespoke kernel, before building
anything on the assumption that it is.

Not part of the package. Nothing here is built or installed.

## Running it

    pip install slangpy              # in its own venv; see the note below
    VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/radeon_icd.x86_64.json \
        python spike.py

Two environment traps, both cost an hour to find:

- **slangpy must be imported before numpy.** Importing numpy first makes
  Vulkan device creation fail with "No adapters found" -- a symbol clash
  between numpy's bundled libraries and the LLVM Mesa uses. This is a
  spike-only problem: the shipped library would dlopen Vulkan itself with
  no C++ runtime of its own, and a direct ctypes probe behaves the same
  with and without numpy loaded.
- **Buffers must be ENTRY-POINT parameters, not globals.** slangpy binds
  dispatch kwargs to entry-point parameters; global `StructuredBuffer`
  declarations silently bind nothing and every kernel writes zeros.

## What it measures

Three entry points so the question is measured rather than argued:

- `fused` -- multiply, inverse transform, peak scan in one dispatch,
  writing ONE record per pair
- `corr` + `reduce` -- the honest alternative: transform to global memory,
  then a second pass to find the peak. This is what calling a vendor FFT
  and reducing afterwards costs.

## Results, Radeon 8060S (gfx1151, 40 CU, RDNA 3.5), 8 x 64 pairs

Correctness first: **512 of 512 peak indices exact** against a float64
numpy reference, max relative error on the magnitude 2.7e-07, which is
float32 rounding. An injected signal at lag 611 comes back at lag 611.

    n=1024   fused 0.035 ms   842 GFLOP/s      corr+reduce 0.057 ms   1.63x
    n=2048   fused 0.094 ms   680 GFLOP/s

**Fusion pays, and for the predicted reason.** The unfused path runs at
158 GB/s against a measured device ceiling of 187 -- it is bandwidth-bound,
exactly as the roofline in the plan said it would be. The fused path sits
at 17 GB/s and is not.

## Optimisation passes, including the ones that failed

    pass                          n=1024        note
    radix-2, WG=256               0.044 ms      starting point
    precomputed twiddle table     0.076 ms      WORSE: +8 KB of LDS costs
                                                more occupancy than the
                                                transcendentals cost
    WG 64 / 128 / 256 / 512       0.100 / 0.061 / 0.044 / 0.050
                                                256 is the optimum
    radix-4                       0.035 ms      -26%: five stages instead
                                                of ten, half the barriers
    drop the ping-pong copy       0.037 ms      a wash; the conditional
                                                read costs what the copy
                                                saved

842 GFLOP/s is **15.5% of the 5427 GFLOP/s** this device measured on a
dependent-free FMA chain, so there is roughly 6x still on the table.

## What this found that the plan did not anticipate

- **Mixed radix is mandatory, not an optimisation.** Radix-4 only covers
  N = 4^k. At n=2048 it silently returned the wrong answer for 473 of 512
  pairs -- the library supports odd powers of two, so a radix-2 stage has
  to run first. Fixed and verified.
- **LDS caps this structure at n=2048.** Double-buffered Stockham needs
  2*N*8 bytes: 32 KB at n=2048 and the entire 64 KB budget at n=4096,
  which does not launch. So the four-step decomposition is needed at
  n>=4096, not at n=1048576 as the plan implied -- and that is the same
  decomposition the CPU already uses, for the same reason in a different
  memory.

## How close to optimal? Against rocFFT, not against FMA peak

"15% of FMA peak" says nothing on its own: an FFT is LDS- and
bandwidth-bound, not FMA-bound. `rocfft_ref.py` measures AMD's own tuned
library on this device for the same 512 inverse transforms of length 1024:

    rocFFT          0.0517 ms   transform only
    fused kernel    0.035  ms   transform + conjugate multiply + peak scan

**1.48x faster than rocFFT while doing strictly more work**, and the gap
would widen once rocFFT is given the multiply and reduction kernels it
would need alongside. rocFFT moves 8 MB per dispatch and runs at 155 GB/s
against this device's 187 GB/s ceiling -- it is bandwidth-bound, which is
the whole argument for fusing. rocFFT reaches 9.3% of FMA peak on this
problem; we reach 15.5%. So the yardstick was wrong, not the kernel.

## The hierarchical filter, fused across a batch tile

`hierarchical.slang`. One workgroup owns a tile of the batch and does both
stages without leaving the workgroup: every coarse transform in the tile at
once with all lanes busy, then the survivors IN THAT TILE one at a time at
full length and full thread count. No compaction through global memory and
no second dispatch.

Measured at 8192 pairs (32 data x 256 templates), n=1024, coarse band 256,
inspiral-like reference with a seismic knee, in-band fraction 0.988:

    flat, every pair at full length      0.467 ms   8192/8192 peaks exact
    hierarchical, 6.8% escalating        0.238 ms   1.96x, 0 missed, 0 invented
      of which the coarse pass alone     0.180 ms

Correct is the first claim: no peak above threshold is missed and none is
invented, at every coarse threshold tried.

## Two traps this cost, both worth remembering

**Batch size decides the answer.** At 512 pairs the hierarchical filter was
3x SLOWER than flat, and the reason was not arithmetic: tiling cuts the
workgroup count, and 128 workgroups do not fill 40 CUs. At 8192 pairs it is
2x faster. Any measurement of a tiled GPU kernel on a batch that does not
fill the device is measuring occupancy, not the algorithm.

**A stale constant made the baseline meaningless.** The flat kernel's
length was left at 2048 from an earlier sweep while the data was 1024, and
it reported a baseline 2.8x too slow -- which would have flattered the
hierarchical result to 5.6x. It was caught only because the same harness
also prints how many peak indices match the float64 reference, and it said
9 of 8192. Every timing here is paired with that check for exactly this
reason.

## Where the remaining performance is

Both phases carry about 2x of overhead against their own ideal:

    phase 1  0.180 ms measured against ~0.093 ms if it cost the 1/5 of a
             full transform that its size implies
    phase 2  0.058 ms measured against ~0.032 ms for 6.8% of the flat work

Three things to try, in the order they look worth it:

1. **Register-resident coarse transforms.** 256 points over 32 threads is 8
   points per thread -- a radix-8 butterfly in registers with ONE trip
   through LDS, instead of four stages each reading and writing it. This is
   the CPU's four-step idea (independent transforms in the lanes) applied
   to the small pass.
2. **Data and template reuse across a tile.** Every pair currently reloads
   both spectra from global memory. A (d_tile x t_tile) tile reads
   d_tile + t_tile spectra to do d_tile * t_tile pairs; the roofline work
   in docs/plans/gpu.md puts the span of that choice at 7x.
3. **Load balance in phase 2.** Survivors are Poisson across tiles, so a
   tile with three costs three times one with none, and the dispatch waits
   for the worst. A global worklist with a second dispatch balances
   perfectly at the cost of the round trip the current design avoids --
   which of those wins is a measurement, and it will depend on escalation
   rate.
