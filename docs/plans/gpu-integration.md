# Getting the GPU path into the library

The spike answered its questions: fusion pays 1.63x over transform-plus-
reduce, the four-step maps onto shared memory the way it maps onto cache,
and the filter runs 49x a CPU core with the hierarchical mode giving the
same 6-8x over flat that it gives on the CPU. What is in `gpu/` is not a
backend -- it is four kernels, a benchmark harness, and a set of findings.

This is the plan to make it one. Nothing below is built.

## 1. Portability, before anything else

Two hazards, both found by audit rather than by a crash, and both settled
before more kernels are written.

**Subgroup width is not 32.** Five sites assumed a 16-lane slot sits
inside one wave. True at wave32/wave64, warp 32 and Apple's SIMD group 32;
false on Intel, where SIMD8 makes the slot straddle two subgroups and the
shuffles read lanes that do not exist. Quietly wrong, no crash. The
transpose now branches on `WaveGetLaneCount()` -- uniform across the
workgroup, so a scalar compare rather than divergence -- and falls back to
threadgroup memory below 16 lanes. Every remaining wave-dependent site
gets the same treatment, and the reduction helpers get a single shared
implementation so there is one place to be wrong.

**Threadgroup memory is 32 KB on Apple, 64 elsewhere.** Every kernel is
budgeted to 32 KB. The current one uses 9 KB, so this costs nothing today,
but it becomes a hard constraint when the larger transform lengths arrive
and it is cheaper to honour from the start than to retrofit.

**Register pressure is device-dependent and must be asked about, not
assumed.** RDNA gives 256 VGPRs a thread, NVIDIA 255, Apple and Intel
differ, and occupancy falls away differently on each, so a kernel that
fits here proves nothing about elsewhere. Vulkan reports register counts,
spills and occupancy per pipeline through
VK_KHR_pipeline_executable_properties; CUDA through cudaFuncGetAttributes;
Metal through pipeline reflection. The backend queries it at pipeline
creation, beside the subgroup-width query, and a variant that spills is
rejected in favour of one that does not.

**The rule stays the same as the CPU's.** Where a device does not meet a
requirement the library refuses and says which, rather than running
something it cannot vouch for.

## 1b. One API, and constants fixed at pipeline creation

**Specialization constants, not a blob per configuration.** Slang's
`[SpecializationConstant]` survives to both targets that matter:

    SPIR-V   OpDecorate %CHUNK SpecId 1
             %CHUNK = OpSpecConstant %uint 4
             %45 = OpSpecConstantOp %uint UDiv %uint_16 %CHUNK
    Metal    constant uint fc_LANES [[function_constant(0)]];

Derived expressions fold as well, so subgroup width, chunk size and level
count are all set from what the device reports, at pipeline creation, from
ONE embedded blob. CUDA has no equivalent and would need a variant per
configuration, which is free there because the driver JITs PTX anyway.
(HLSL rejects them for an unrelated Slang reason; we do not target it.)

**Vulkan only, to start.** Vulkan is native on AMD, NVIDIA, Intel and
Android, and reaches Apple through MoltenVK. Everything these kernels use
-- storage buffers, workgroup memory, barriers, subgroup ops,
specialization constants -- maps onto Metal, so the translation should
carry it. That buys one RHI, one blob format, one code path and one set of
bugs, against a vendored MoltenVK dylib in the macOS wheel and Apple
performance going through a translation layer.

This is a cheap bet precisely because the Slang source already compiles to
native Metal and CUDA, verified. If Apple through MoltenVK disappoints
when it can be measured, moving that platform to native Metal is a build
change rather than a rewrite. That is the payoff from the authoring layer
-- not using every target today, but making the choice reversible.

## 2. Every supported length, in three tiers

The library supports 1024 and the powers of two to 1048576. One kernel
shape does not cover that range, because what a workgroup can hold changes
with it. Three tiers, chosen by the same measured-not-modelled rule:

**Tier A, n <= 4096.** What exists now. 256 threads, 16 points each, the
whole transform in registers; threadgroup memory only for the transposes,
chunked to 8 KB. n = 4096 is 16x16x16, n = 1024 is 16x64, n = 2048 and
8192 need one radix-2 stage because they are odd powers of two -- the
coarse pass already does this and it generalises.

**Tier B, 8192 <= n <= 65536.** Too big for 16 points per thread. Either
more points per thread (32 points = 64 VGPRs, which will cost occupancy)
or more threads per transform (512, 1024). Which one wins is a
measurement, and it may differ by device, which is exactly what the cost
table is for.

**Tier C, n > 65536.** Cannot live in one workgroup at all. The classic
large-FFT answer: four-step across DISPATCHES, with global memory between
the passes. Bandwidth then matters in a way it has not so far, and the
fusion argument has to be re-made at that size rather than assumed --
possibly the peak scan fuses into the last pass only.

Tier A is done. Tier B is the next work. Tier C can wait: the pycbc search
uses 4096, and the benchmark grid's largest lengths are the least urgent.

## 3. Tables, per device

The CPU has two tables for a reason that carries over exactly:

**accuracy** is a property of the ALGORITHM -- decimation, coarse
threshold, taps, margin -- and nothing in it is architecture-dependent. It
should transfer to the GPU unchanged, which matters because it is the
expensive one: hours to generate, where cost is about forty minutes. If it
transfers, adding a device costs a cost table.

That is a hypothesis with a cheap test and it gets tested, not assumed:
run `measure()` against the GPU backend and compare cell by cell. Two
things could break it and both are worth looking for specifically --
different FMA contraction flipping pairs that sit exactly at the coarse
threshold, and any difference in which sample wins a tie in the peak
reduction.

**cost** is a property of the MACHINE and does not transfer at all. Worse,
its SHAPE changes: escalation on a CPU costs roughly linearly in the
escalation rate, while on a GPU it is a step in how many workgroups the
survivor list fills, plus a fixed cost paid even when nothing escalates.
So `choose_config` needs a device-aware cost model, not merely
device-specific rows in the CPU's model.

### How the files work

Same philosophy as `cost.txt`: measured, in a file, regenerable, and the
library refuses where it has no measurement.

    python/matchedfilter/data/
      accuracy.txt              shared; algorithm property
      cost.txt                  CPU, this machine
      gpu/generic.txt           conservative fallback, any device
      gpu/amd-gfx1151.txt       measured here
      gpu/nvidia-sm89.txt       ... as they are measured

Keyed on a device identity string the driver already reports -- vendor,
architecture, compute-unit count -- normalised so that two cards of the
same architecture share a table. Lookup order: exact device, then
architecture, then `generic.txt`. `MF_GPU_COST` overrides, as `MF_COST`
does today.

`generic.txt` is the interesting one. It cannot be right for every device,
so it is not allowed to pretend: it holds the RELATIVE costs measured here
with a wide margin, is marked as a fallback in its header, and selection
records that it used a fallback so a caller can see it. The alternative --
refusing on unmeasured hardware -- is too strict for a library that should
run out of the box, but it must not silently look like a measurement.

A device table is cheap to generate, which is the point: one command, tens
of minutes, and `tools/hmf_tune.py --device` writes it.

## 4. The backend seam

`MatchedFilter` and `HierarchicalFilter` keep their API exactly. The
device is chosen the way the SIMD target already is -- probed, overridable,
and reported:

    matchedfilter.targets()      # gains 'vulkan', 'metal', 'cuda'
    matchedfilter.backend()      # says which was selected
    matchedfilter.set_target()   # forces one
    MF_DEVICE=cpu|vulkan|...

Drivers are opened with `dlopen` at first use, never linked, so a wheel
built with GPU support still installs and runs on a machine with no GPU --
the backend simply is not in `targets()`. Device code is compiled AOT in
CI and embedded: SPIR-V, a metallib, PTX. No runtime shader compiler,
which is what keeps it to one wheel.

Peak-only output means the return trip is already tiny. The input is the
part that matters, so device buffers are accepted directly through
`__cuda_array_interface__` and DLPack -- protocols, not dependencies --
so a caller already holding spectra on the device hands over a pointer.
Host arrays keep working.

## 5. Testing

The existing suites are the asset: they must pass against the GPU backend
unchanged, and the precision harness already compares against a float64
reference, which is exactly what a new backend needs.

Bit-exactness across devices is not achievable and will not be claimed.
What can hold is the guarantee the hierarchical filter already makes --
the peaks reported are the peaks the flat filter OF THE SAME DEVICE would
report, exactly -- plus a stated tolerance between devices.

CI runs the SPIR-V path on lavapipe, which is far too slow to benchmark
and entirely adequate to prove correctness, so every push checks the GPU
kernels compute the right answer without a GPU runner. Performance is
measured deliberately, on real hardware, the way the tuning tables already
are.

And one lesson from the spike goes into the harness rather than the notes:
every timing is printed next to a count of peak indices matching a float64
reference. Three silent bugs were caught that way -- a gather/scatter
race, a wave-width assumption, and a buffer overrun -- and none of them
would have failed a benchmark.

## Order

1. Portability seam and the shared wave helpers. Small, and everything
   else sits on it.
2. Tier B lengths, measured both ways.
3. The device cost table format, the generic fallback, and
   `tools/hmf_tune.py --device`.
4. The backend seam and AOT packaging, on one device.
5. Test the accuracy-table-transfers hypothesis. It decides what every
   later device costs.
6. A second device. That is what proves the authoring layer paid for
   itself.
7. Tier C, if the largest lengths turn out to matter.
