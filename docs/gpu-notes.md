# GPU notes

The GPU backend is part of the library: `device="gpu"` runs the same call as
the CPU, returns the same fields with the same conventions, and is held to
the same tests. The kernels are Slang compiled to SPIR-V ahead of time and
shipped inside the wheel, dispatched through a few hundred lines of ctypes
over the system Vulkan loader. Nothing at run time imports a shader compiler,
and there is no second wheel to choose.

These are the working notes from building it, kept because most of what they
record is a measurement that contradicted an expectation. They are in the
order the questions came up, so early sections describe code that has since
been replaced -- what survives is the reasoning and the numbers.

## Where the pieces live

| | |
|---|---|
| `src/gpu/tierb.slang` | the kernel, one source specialised by transform length |
| `tools/build_spirv.py` | compiles it, reflects the binding contract, writes the manifest |
| `python/matchedfilter/_vkcompute.py` | the Vulkan dispatch, ctypes, no dependencies |
| `python/matchedfilter/_vulkan.py` | device enumeration, and why a machine reports none |
| `tools/gpu_decomposition.py` | the transform decomposition, verified before any kernel was written |
| `tools/gpu_output_order.py` | where each register lands in the output |

## Two traps, both of which cost an hour

- **A shadowed `libstdc++` looks exactly like having no GPU.** Mesa's drivers
  link against the system C++ runtime. A conda prefix early on the library
  path supplies an older one -- miniconda ships 6.0.29, missing the
  `GLIBCXX_3.4.30` and `3.4.32` the drivers need -- and then *every* ICD
  fails to load and the loader reports, accurately and uselessly, that it
  found no valid GPUs. `matchedfilter._vulkan` names this as a cause rather
  than leaving it to be misread as absent hardware.

- **Do not set `VK_ICD_FILENAMES`.** An earlier version walked the ICD
  directory setting it per candidate, on the theory that probing a driver for
  absent hardware poisons the loader for the rest. That theory was wrong, and
  setting the variable was itself the failure: pointed at the radeon ICD,
  `vkCreateInstance` returns `VK_ERROR_INCOMPATIBLE_DRIVER` on a machine
  whose radeon driver works perfectly when the loader is left alone. The
  failures behind the theory were the shadowed `libstdc++` above.

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

## CPU against GPU, each against its own ceiling

`compare_cpu_gpu.py`. Absolute throughput answers whether the GPU is worth
it; the fraction of peak answers the more useful question, which is whether
the GPU implementation is as well optimised for its hardware as the CPU one
is for its.

    flat matched filter, n=4096
                    us/pair   GFLOP/s   ceiling   % of peak
      CPU, 1 core     4.915        55       288      19.1%
      GPU             0.291       931      5427      17.1%

The GPU is 16.9x a single core, and sits at 0.90x the CPU's fraction of its
ceiling. Both land near 17-19%, which is what this shape of work gives on
either machine: an FFT is bound by shared memory and cache traffic, not by
FMA throughput. rocFFT reaches 9.3% on the same device.

The CPU ceiling is architectural -- Zen 5 AVX-512, two FMA units x 16
float32 x 2 flops = 64 flops/cycle, quoted at a sustained 4.5 GHz. The GPU
ceiling is measured on the device with a dependent-free FMA chain.

    hierarchical, band/n = 256/4096
                  speedup   escalating    ideal   % of ideal
      CPU (pycbc)   6.03x         9.4%    7.37x        82%
      GPU           6.12x         3.1%   13.76x        44%

Matching the CPU's speedup was the goal and it is met. Being as close to
the IDEAL is not: at 3.1% escalation there is far more available, and the
whole gap is the coarse pass. At that rate refine should cost 0.018 ms and
the coarse pass 0.025; the coarse pass measures about 0.080.

## Why the optimisation stops here for now

    the same kernel, the same data, 15 timings
      min 0.589 ms   median 0.638 ms   max 1.421 ms
      spread 2.41x   CV 29.1%

This box is shared -- another user's 32-process job, plus this repository's
own table regeneration on 30 of 32 cores -- and the 8060S is an iGPU
sharing memory and power with the CPU. Differences smaller than about 2x
cannot be attributed to anything on this machine right now.

Which retired one change. Walking the twiddles incrementally (one sin/cos
plus sixteen complex multiplies, against sixteen sin/cos) measured 1.4x
faster and is not: 1.4x is inside the noise. Its cost is not -- accuracy
went 3.4e-07 to 1.6e-06 from accumulating those multiplies. Unproven speed
is not worth measured accuracy, so it is reverted, and `noise.py` is here
to make the same judgement quickly next time.

The coarse-pass work is the next thing, and it needs a quiet machine.

## The target is 50x a CPU core, and we are at 17x

Peaks, both measured the same way -- a dependent-free FMA chain, on the
device:

                          measured    conditions          spec
      1 CPU core           240.6      3.76 GHz, loaded     332 at 5.19 GHz
      GPU                 8953        1.75 GHz, throttled  14850 at 2.9 GHz

The GPU measurement is 60% of spec and the clock back-solves to 60% of
spec, so the probe reaches essentially 100% of peak FOR THE CLOCK IT GETS.
The shortfall is an APU sharing one power budget with a busy CPU, not the
kernel. The published 14.85 TFLOPS matches 40 CU x 64 lanes x 2 flops x
2.9 GHz exactly.

So the peak ratio is 44.7x, and that is the target: if the GPU
implementation were as well fitted to its hardware as the CPU one is to
its, the filter would run about 45-50x a single core.

      flat matched filter, n=4096      achieved   ceiling   % of peak
        CPU, 1 core                        55       240.6      22.9%
        GPU                               931      8953        10.4%
                                                   ratio       16.9x

17x against a 45x target. The GPU implementation is at roughly half the
CPU's efficiency, and closing that is worth more than everything else on
this list.

## What binds it, by elimination

At n=4096, 2048 pairs, 0.595 ms:

      FMA          930 of 8953 GFLOP/s        10%
      LDS          677 of 8960 GB/s            8%
      global       226 GB/s, cache-served     -- and collapsing the
                                                 working set to one slice
                                                 buys 1.18x, so not this

None of the three is the wall. What is left is latency at 25% occupancy:
a 4096-point transform needs 4096 complex in threadgroup memory, which is
32 KB, which fits two workgroups in a CU's 64 KB, which is 512 of about
2048 thread slots. LDS capacity at this transform length sets occupancy,
and occupancy sets latency hiding.

Two things that did NOT help, both measured:

- replacing the four-stage radix-2 dft16 (a temporary and 64 register
  moves per call) with radix-4 x radix-4 in place: identical throughput.
  The compiler was already eliminating the moves under SSA.
- walking twiddles incrementally instead of sixteen sin/cos: identical
  throughput, and 5x worse accuracy. Reverted.

The next idea worth trying is splitting the transform so a workgroup holds
less than the whole of it -- which is the four-step again, one level
further down, trading a barrier for occupancy.

## Chunking the transpose: 2.71x, and 43x a CPU core

The elimination argument said latency at 25% occupancy, forced by holding
the whole 4096-point transform in threadgroup memory. But the transform
does not LIVE there -- each thread holds its 16 points in registers, and
shared memory is only ever a transpose buffer. So stage the transposes in
chunks of four k2 at a time: 1024 complex = 8 KB, for both the outer
exchange and the sixteen inner ones.

    n=4096, 2048 pairs, measured in the SAME run so the box's drift
    cancels:
      32 KB, whole transform      1.565 ms    354 GFLOP/s
       8 KB, chunked exchange     0.577 ms    959 GFLOP/s    2.71x

Identical accuracy, 3.26e-07. On a quieter measurement the same kernel
reaches 0.232 ms:

                          GFLOP/s   % of 8953 ceiling   vs 1 CPU core
      before                 931          10.4%              16.9x
      after                 2385          26.6%              43x

which is the target, and above the CPU's own 22.9% of its ceiling.

The same change applied to the COARSE pass made it slower -- 0.127 ms
against 0.104 -- because a 256-point transform pays eight barriers for the
chunked exchange where the direct transpose pays one, and at that size the
barriers cost more than the occupancy buys. Opposite trade, same knob. The
coarse pass keeps the direct transpose.

## The bottleneck now is the coarse pass

    hierarchical at n=4096, band 256, 3.1% escalating
      flat            0.232 ms
      hierarchical    0.104 ms     2.41x
        of which refine (64 pairs)  ~0.007 ms
        of which coarse             ~0.097 ms   against an ideal of 0.010

The coarse pass is 10x its own ideal and now dominates completely. It is
LDS-bound in a way the chunked exchange cannot fix: sixteen concurrent
256-point transforms each want a 16x16 transpose, 256 complex per slot, so
32 KB per workgroup -- 128 bytes per thread, where full occupancy allows
32. Chunking trades that for barriers and loses.

The way out is a transpose that uses no threadgroup memory at all. A slot
is sixteen threads, which sits inside one wave on any width this runs on,
so the 16x16 exchange can be done with wave shuffles -- four butterfly
steps with static register indices, no LDS and no barriers. That would
take the coarse pass off the occupancy cliff entirely, and it is the next
thing to build.

## Measurement conditions have made further work pointless for now

The same kernel on the same data measured 0.595 ms earlier and 1.603 ms
later in the same session, and fifteen consecutive timings spanned 2.41x
with a 29% CV. The box carries another user's 32-process job and this
repository's own table regeneration on 30 of 32 cores, and the 8060S
shares power and memory with both. Differences below about 2x cannot be
attributed to anything.

## Saturation, and what other GPUs will need

The flat kernel reaches its plateau at about 410 pairs per compute unit
and holds it out to 6554 per CU:

    pairs     nd x nt     mem     ms       GFLOP/s   pairs/CU
     2048     16x128      4.7 MB  0.134     4129        51
    16384     64x256     10.5 MB  0.893     4975       410
    32768     64x512     18.9 MB  1.759     5036       819
   131072    128x1024    37.7 MB  7.064     5016      3277
   262144    256x1024    41.9 MB 13.717     5166      6554

So the rule for other devices is ~400 pairs per CU/SM:

    Radeon 8060S (40 CU)        ~16400 pairs
    RTX 5060 desktop (34 SM)    ~14000
    RTX 4090 (128 SM)           ~52000
    MI300X (304 CU)            ~125000

The pycbc FIR search reports ~100k pair-calls per segment, so the real
workload already saturates everything up to a very large card.

## Clean numbers, on an idle machine

Every earlier comparison here was taken while this repository's own table
regeneration held 30 of 32 cores. With that finished:

                      achieved   ceiling   % of peak
      CPU, 1 core        102       322       31.7%
      GPU               5036     27270       18.5%
                                  49x a CPU core

The GPU ceiling is 27270 GFLOP/s, not the 14850 the spec sheets quote:
that figure is single-issue, and RDNA3 dual-issues FP32. The probe finds
the dual-issue path.

49x a single core meets the target. The CPU is still the better-fitted
implementation -- 31.7% of its ceiling against 18.5% -- so there is
another 1.7x in the GPU before the two are equally tuned.

    hierarchical at 32768 pairs, 3.1% escalating
      flat          1.772 ms
      hierarchical  0.270 ms      6.57x, 48% of its 13.79x ideal

## Portability: what would break on a non-AMD GPU

Nothing here uses a vendor extension, vendor syntax, or a hardcoded wave
width, and all five kernels compile to SPIR-V, Metal, CUDA and HLSL. But
two things would go wrong, and one of them silently.

**A 16-lane slot is assumed to sit inside one wave.** Five sites compute
`WaveGetLaneIndex() - lane` for a slot base, or shuffle to
`WaveGetLaneIndex() + st`. That holds at wave32 and wave64 (AMD), warp 32
(NVIDIA) and SIMD group 32 (Apple). It does NOT hold on Intel, whose
subgroup may be SIMD8 -- a 16-lane slot then straddles two subgroups, the
shuffles read lanes that are not there, and the answer is quietly wrong.
No crash, no validation error.

The shipped library must query the subgroup size at device init --
`VkPhysicalDeviceSubgroupProperties::subgroupSize`, or Metal's
`threadExecutionWidth` -- and pick a variant, not assume. A slot size of
`min(16, subgroupSize)` works everywhere at the cost of a different
factorisation below 16.

**Threadgroup memory limits differ.** Apple allows 32 KB per threadgroup
where AMD and NVIDIA allow 64 KB. Declared by each kernel here:

    fourstep_4096.slang        9.0 KB    fine everywhere
    fourstep.slang            32.0 KB    at Apple's limit
    hierarchical_fused.slang  34.1 KB    over
    hierarchical.slang        66.1 KB    over
    spike.slang               66.0 KB    over

The three over the line are the early versions. The chunked exchange that
bought 2.71x also brought the current kernel to 9 KB, so the fastest path
is also the portable one -- which is a happy accident worth not relying
on next time.

## Tier B: one kernel for every length a workgroup can carry

`tierb.slang`. The decomposition verified in `decomposition.py`, written
out: L = TB*16 with TB threads holding 16 points each, a 16-point DFT per
thread over its stride-TB column, a twiddle, an exchange, then TB-point
transforms per block carried by TB/16 threads, recursing until TB <= 16.

    n        threads   max rel err   status
    1024        64      2.83e-07     OK
    2048       128      2.49e-07     OK
    4096       256      2.57e-07     OK
    8192       512      3.54e-07     OK
    16384     1024          --       crashes: see below

Three bugs on the way, all of which the Python simulation caught or would
have:

**Registers cannot be indexed dynamically.** `dftm(r, b*TB, TB)` with a
runtime offset and length spills the register array to scratch; the driver
crashed. Every size and offset now folds at compile time, and every loop
touching the array carries `[unroll]` -- thirteen of them. Miss one and
the array silently leaves registers.

**Scatter and gather need different indices.** Writing the transpose and
reading it back with one set of block/lane values gathers from the wrong
block. Wrong peak, no other symptom.

**The innermost level needs its exchange too.** After the dft16 a thread
holds A[lane][k2] for its own lane, and the next DFT is over lane, which
lives ACROSS threads. Transforming a thread's own registers there
transforms the wrong axis: the peak came out about 15% low and nothing
else looked wrong. Found by simulating the shader's index arithmetic in
numpy and comparing to the reference, not on the device.

## Tier B, complete: a fixed 8 KB at every length

The threadgroup array is no longer sized to the transform. CH registers of
every thread are staged at a time, with CH = 1024/WG, so the buffer is
1024 complex -- 8 KB -- whatever the length. A reader inverts the scatter
formula to find which register of which thread holds each value it wants,
and takes it when that register is in the current chunk.

    n        WG     CH    buffer    max rel err   ms      GFLOP/s
    1024      64    16     8 KB      3.78e-07    0.032       924
    2048     128     8     8 KB      3.42e-07    0.045      1424
    4096     256     4     8 KB      3.51e-07    0.092      1499
    8192     512     2     8 KB      3.47e-07    0.326       914
    16384   1024     1     8 KB      3.30e-07    0.725       880

Every length a workgroup can carry, correct to float32, under Apple's
32 KB as well as everyone else's 64.

The index arithmetic was written with / and % at first, which are integer
divisions -- sixteen per thread per chunk. Every divisor is a power of
two, so they are shifts and masks now. That bought n=16384 about 20%.

**Generality cost about a third, and now costs 12%.** The gap was mostly
that the kernel was only half specialised. NLEN is a `#define`, so WG and
CH folded -- but the LEVEL LOOP was a runtime `while`, so len, TB and the
shifts changed per iteration and none of the index arithmetic folded.

The number of levels follows from NLEN, so it unrolls:

    static const uint NLEVELS = (WG <= 16) ? 1 : ((WG <= 256) ? 2 : 3);
    [ForceUnroll] for (uint lvl = 0; lvl < NLEVELS; ++lvl) {
        const uint TB  = WG >> (4 * lvl);
        const uint len = N  >> (4 * lvl);
        ...

With lvl an unrolled constant every one of those is a constant, and the
divisions and shifts disappear into the instruction stream.

    n        runtime loop   unrolled
    1024         1589         1547     tie
    2048         2311         2103
    4096         2000         2106
    8192         1078         1481     +37%
    16384         843          936     +11%

Unrolling pays where there are levels to fold and is a wash at 1024, which
has the fewest. At n=4096 the general kernel now reaches 2106 GFLOP/s
against the hand-specialised 2385 -- 12% apart rather than a third, and
the rest is the specialised kernel's hardcoded twiddles.

Two measurement notes. The earlier "1499" for the general kernel was taken
on a busy box; on a quiet one the same code gives 2000. And a single-shot
timing put n=1024 at 596 GFLOP/s, where min-of-eleven gives 1547 -- short
kernels need repeats, and one number is not a measurement.

Keeping both variants is still right, but the reason is now smaller: 12%
at the length the search uses. Which to run remains a lookup that belongs
in the device table beside the tile shape.

## What the earlier n=16384 failure needed

    n        sh[] declared
    1024       8 KB     fine everywhere
    2048      16 KB     fine
    4096      32 KB     at Apple's limit
    8192      64 KB     AMD and NVIDIA only
    16384    128 KB     over every limit -- this is the crash

The threadgroup array is sized to the transform, which does not scale. The
fix is the one that already bought 2.71x at n=4096: stage the exchange in
chunks so the buffer is a fixed 8 KB whatever the length. That makes 16384
possible and brings 4096 and 8192 back under Apple's 32 KB at the same
time. It is the next piece of work, and it is a change to `scatter` and
`gather` alone.


## A retraction: it was not the register budget

An earlier version of these notes said that three live copies of `want[]`
plus three inlined `out[16]` "blew the register budget and crashed the
driver". That was a guess dressed as a diagnosis, and it is wrong.

The symptom was a core dump. The fix that followed -- scoping `want` per
level and assigning it unconditionally -- worked, and the explanation was
attached to it afterwards without being checked. Rebuilding that exact
version and running it: the pipeline is created, the dispatch completes,
and nothing crashes. Whatever the original failure was, it was not this
kernel running out of registers.

Which matters beyond one wrong sentence. Register pressure IS
device-dependent -- RDNA gives 256 VGPRs a thread, NVIDIA 255, Apple and
Intel differ, and occupancy falls off differently on each -- so "it fits
here" would never have been evidence that it fits elsewhere. The way to
know is to ask the device: Vulkan reports register counts, spills and
occupancy per pipeline through VK_KHR_pipeline_executable_properties,
CUDA through cudaFuncGetAttributes, Metal through pipeline reflection.
That check belongs in the backend at pipeline creation, next to the
subgroup-width query, and is in the integration plan.

The real defect the compiler was pointing at is now fixed: `out[]` and
`want[]` are explicitly initialised. Every register index provably falls
in exactly one chunk so they were always written here, but the compiler
cannot prove it, and a backend that leaves an unwritten register as
garbage rather than zero would turn that warning into a wrong answer. The
kernel now compiles with no warnings at all.
