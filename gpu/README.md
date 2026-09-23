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

## It is not bandwidth, and the arithmetic said it was

The coarse pass reads 33.6 MB per dispatch for 8192 pairs and ran at 186.4
GB/s against a device ceiling of 186.8 -- apparently saturated, and
apparently 57x redundant, since the algorithm only needs the 0.59 MB of
distinct low-band spectra.

Both numbers are true and the conclusion drawn from them was wrong.
`cache_probe.py` rewrites the pair indices so every pair reads the SAME two
slices: identical arithmetic, identical barriers, but a working set of two
lines that certainly sits in cache.

    normal, 57x redundant reads     0.2597 ms
    every pair reads one slice      0.2241 ms     1.16x

Removing ALL redundant traffic buys 16%. If bandwidth were the wall it
would buy something near 57x. The 576 KB of distinct spectra were already
being served out of a 32 MB Infinity Cache, and 186 GB/s was a coincidence
of the arithmetic rather than evidence of saturation.

This is the algorithm working as designed. Batching means each spectrum is
read by many pairs, and peak-only output means the D x T x n correlation is
never written -- so by construction the filter should not be near the
bandwidth wall, and it is not. What remains is LDS traffic, barriers and
occupancy, which is a different problem with different fixes.

The lesson worth keeping: an achieved bandwidth that matches the ceiling is
not evidence of being bandwidth-bound. It can be a coincidence, and here it
was. The cheap way to tell is to collapse the working set and see whether
anything changes.

## Where the remaining performance is

Both phases carry about 2x of overhead against their own ideal:

    phase 1  0.180 ms measured against ~0.093 ms if it cost the 1/5 of a
             full transform that its size implies
    phase 2  0.058 ms measured against ~0.032 ms for 6.8% of the flat work

Three things to try, in the order they look worth it:

1. **Bigger radix, fewer LDS exchanges.** This is now the main lever, since
   fetching is not. A radix-4 stage reads four complex and writes four for
   about 34 flops; at 256 points that is four stages and four barriers.
   Radix-16 with 16 points per thread is two stages and two barriers for
   the same transform, at 32 VGPRs of register pressure. Same idea as the
   CPU's four-step: hold an independent sub-transform in the lane and only
   go through the shared memory to transpose.
2. **Data and template reuse across a tile** -- worth at most 1.16x on the
   coarse pass, measured, so it is now a low priority rather than the 7x
   the roofline suggested for an unfused design. Keep it in mind for the
   full-length pass, where the traffic per pair is four times larger.
3. **Load balance in phase 2.** Survivors are Poisson across tiles, so a
   tile with three costs three times one with none, and the dispatch waits
   for the worst. A global worklist with a second dispatch balances
   perfectly at the cost of the round trip the current design avoids --
   which of those wins is a measurement, and it will depend on escalation
   rate.

## Register-resident four-step, and what it did not buy

`fourstep.slang`. The CPU's own decomposition, against shared memory
instead of cache: N = N1*N2, each thread holds a length-16 sub-transform
entirely in registers and does it with no barrier, the two halves meeting
through a single transpose.

    256-point coarse transform, 8192 of them
      radix-4 Stockham, four LDS stages     0.180 ms
      register four-step, one transpose     0.080 ms     2.25x

Correct to 3.4e-07, which is float32.

**It did not make the fused kernel faster.** Dropped into the
tile-fused hierarchical kernel it went 1.96x -> 1.86x against flat. The
transform is faster; the kernel is not, because a single kernel makes both
phases share one register and LDS budget:

    separate bB buffer          40 KB LDS   phase 1 cost 0.216 ms
    bB folded into bA           32 KB       still 0.216 ms
    LDS reduction -> shuffles   32 KB       0.202 ms
    ... against 0.080 ms for the same transform in a kernel of its own

Phase 2's full-length Stockham forces registers to be allocated for it
whether or not any pair escalates, and that is what the coarse pass pays.

So the two-kernel form wins after all, `two_kernel.py`:

    flat                       0.417 ms
    coarse (register)          0.129 ms
    coarse + refine            0.184 ms    2.27x, 0 missed, 0 invented

against the 1.86x of the fused version. Fusing avoids a worklist round
trip through global memory and costs more than the round trip does,
because resource budgets do not separate the way work does.

## Against the CPU's speedup, which is the real bar

The CPU's hierarchical filter reaches 6.03x over flat in pycbc at 9.4%
escalation. The GPU reaches 2.27x. That is not a 3x deficit -- the two are
measured in different regimes, and the ideal differs with them:

    case              band/n   escal.   ideal    measured   % of ideal
    CPU pycbc n=4096    1/16     9.4%   7.37x     6.03x        82%
    GPU spike n=1024    1/4      6.8%   3.73x     2.27x        61%

Both are instruction-bound, so the same benefit should be available. Two
things stand between here and there:

1. **The regime.** Matching the CPU's SPEEDUP means matching its band/n
   ratio, which means n=4096, where the ideal is 9.12x. That needs the
   four-step at full length too -- which LDS forces anyway, since a
   double-buffered 4096-point transform wants the entire 64 KB.
2. **The remaining 39%.** The coarse pass alone is 0.129 ms here against
   0.080 standalone, so the worklist and the second dispatch cost about
   60%. Persistent workgroups pulling from a queue, or an indirect
   dispatch sized to the actual survivor count rather than the whole
   batch, are the obvious next things.

## n=4096, and matching the CPU's speedup

`fourstep_4096.slang`. A double-buffered Stockham at 4096 points wants the
entire 64 KB of threadgroup memory and does not launch, so the four-step is
required rather than merely faster -- and it nests. N = 256*16 where the
length-256 half is itself a 16x16 four-step, so the whole transform is three
rounds of a 16-point DFT held in registers with two transposes through
shared memory. The CPU's balanced split, applied twice.

Correct to 3.4e-07. LDS 32 KB + 1 KB of reduction scratch.

With the coarse pass at band 256 -- the ratio the CPU's pycbc case actually
uses -- `hier4096.py`:

    2048 pairs, 3.1% escalating, 0 missed, 0 invented
    flat            0.648 ms
    hierarchical    0.100 ms      6.51x

    CPU pycbc, same band/n, 9.4% escalating     6.03x

So the GPU now reaches the speedup the CPU gets, which was the bar. Both
are instruction-bound and the same structural benefit is available to both,
as expected.

There is still 2x in it: 6.51x against an ideal of 13.71x for this
escalation rate is 47%, where the CPU reaches 82% of its own ideal. The
gap is the coarse pass and the reduction, not the transform.

## Three bugs worth keeping, all silent

**A gather/scatter race.** Every round reads its points from shared memory
into registers and writes them back permuted. Without a barrier between,
one thread overwrites an address another has not read. At 256 points this
was invisible because 16 threads run in lockstep inside one wave; at 4096
there are eight waves and it appeared immediately.

**A wave-width assumption.** The cross-wave reduction did
`if (WaveIsFirstLane()) sh[tid / 32] = best`, which assumes wave32. RADV
can compile compute as wave64, and then only every other slot was written
while the rest still held transform output -- so the reported peak came out
LARGER than the true one, which is the one direction a peak finder must
never fail in. Wave width is not a portable constant: Metal's SIMD group is
32, AMD's is 32 or 64 at the compiler's discretion. The reduction is now a
tree through scratch, which costs throughput (1205 -> 863 GFLOP/s) and is
correct on any width.

**A buffer-aliasing overrun.** Phase 2 of the fused kernel takes its two
Stockham buffers as halves of the tile array, which needs TILE*BAND >= 2N.
At TILE=4 that is 1024 < 2048; the halves overlapped and ran past the end.
327 peaks missed and 148 invented, no crash, no validation error.

All three were caught by the same thing: every timing in these harnesses is
printed next to a count of how many peak indices match a float64 reference.
None of them would have been caught by a benchmark alone.
