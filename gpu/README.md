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
