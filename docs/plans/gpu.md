> **Status: done.** This plan has shipped. `device="gpu"` runs the full
> API and the GPU is covered by the same tests as the CPU. Kept for the
> reasoning and the decisions recorded along the way; for how the result
> actually works see [the GPU notes](../gpu-notes.md). Note that what
> this plan calls `gpu/` is now `src/gpu/` for the kernel and `tools/`
> for the development scripts.

# Running on GPUs without giving up the CPU

Plan for review. Nothing here is built.

**Decided: Slang as the authoring layer**, on the evidence in "Choosing the
authoring layer" below -- Khronos governance, a shipping production user
that is not the vendor, and a probe showing the Metal target emits native
`simd_max`, threadgroup memory and atomics for exactly the constructs this
kernel needs. Everything downstream of that decision is still open, and the
phase-1 spike can still overturn it on codegen quality.

## What has to stay true

Four constraints shape every decision below, and three of them are already
properties of the library rather than new requirements.

**One wheel.** `pip install matchedfilter` gives every backend the machine
can use. No `matchedfilter[cuda]`, no picking a wheel, no asking anyone to
install a toolkit. This is the sharpest constraint and it eliminates more
designs than anything else here.

**The CPU path does not regress.** Not by a percent. The Highway kernels,
the four-step split, the measured tables -- untouched. A GPU backend that
costs CPU performance has failed even if it is fast.

**Measured, not modelled.** A GPU has its own cost table, measured on that
GPU, and refuses where it has no measurement. Same rule, new machine.

**Peak-only, single precision.** Both transfer to GPUs better than they do
to CPUs, for reasons in the next section.

## Why this library specifically is worth putting on a GPU

Not every CPU library earns a port. This one does, and the argument is not
"GPUs are fast".

A straightforward batched matched filter writes D x T x n complex samples
and the caller throws nearly all of them away. On a CPU that wastes cache.
On a GPU it wastes the one resource that actually binds -- a 4096-point
correlation of 16 segments against 512 templates is 512 MB of output that
exists only to be reduced to a few thousand peaks. Fusing the forward
transform, the multiply, the inverse transform and the peak scan into one
kernel means that traffic never happens.

That fusion is also why calling cuFFT or rocFFT does not solve this. They
produce the full correlation, which is the thing worth not producing. The
kernel has to be ours.

Single precision throughout is already true, and there is no double path to
port or to explain.

## The wheel constraint, and what it eliminates

To ship one wheel with no toolkit on the user's machine:

- **Driver libraries are opened at run time, never linked.** `libcuda.so.1`,
  `libvulkan.so.1`, `nvcuda.dll`, the Metal framework. Absent driver means
  that backend is unavailable, exactly as an absent AVX3 means that target
  is unavailable today. `targets()` and `backend()` already express this
  idea; they grow a device axis.
- **Device code is compiled at build time and embedded as bytes.** SPIR-V
  for Vulkan, PTX for CUDA (the driver JITs it for the actual architecture,
  so no per-SM cubin zoo), a metallib for Apple. All produced in CI, all
  measured in kilobytes.
- **No runtime shader compiler.** This is the big one. It rules out
  designs that generate kernel source at run time and compile it on the
  spot, because that needs glslang or nvrtc present -- either a user
  dependency or tens of megabytes vendored into the wheel.

The usual objection to ahead-of-time compilation is that it cannot
specialise. Here it can: **the library supports eleven transform lengths**,
1024 and the powers of two from 4096 to 1048576. Eleven, times a handful of
configurations, is a build-time loop, not a combinatorial problem. The
argument for runtime codegen mostly evaporates at that size.

One clarification on "one wheel", because it is worth being exact: wheels
are already per-platform, and a macOS arm64 wheel cannot carry CUDA code
for a machine it will never run on. "One wheel" means no choice *beyond*
the platform tag pip already resolves -- the Linux x86-64 wheel carries
Vulkan and CUDA and HIP device code together, and picks at run time.

## Choosing the authoring layer

### Is Slang the future?

As close to it as this space offers. Khronos took over governance in
November 2024, hosting the compiler NVIDIA had developed since 2017; the
January 2025 Vulkan SDK shipped a release version; Valve integrated it into
Source 2 and ships Slang-generated SPIR-V in Counter-Strike 2 and Dota 2.
Vendor-neutral governance, a shipping production user that is not the
vendor, and inclusion in the SDK people already install is a stronger
position than any alternative single-source layer has.

That matters here beyond fashion. The alternative to a portable authoring
layer is N hand-written kernels, and the cost of those is not writing them
-- it is that an optimisation discovered in one never reaches the others.
This library's whole method is measure, learn, encode; N backends means
learning something N times or letting N-1 rot.

### The comparison

| option | covers | AOT to embeddable IR | risk |
|---|---|---|---|
| **Slang** | Vulkan, D3D12, CUDA, Metal, WebGPU, CPU | yes | Metal and WebGPU targets marked work-in-progress upstream |
| **Vulkan/SPIR-V only, + MoltenVK on Apple** | anything with a Vulkan driver | yes | MoltenVK vendored; Apple runs through a translation layer |
| **VkFFT** | Vulkan, CUDA, HIP, OpenCL, Level Zero, Metal | no -- generates source, compiles at run time | needs a runtime compiler, which the wheel constraint forbids; and it is an FFT library, so the peak scan and the hierarchical pass are ours regardless |
| **Hand-written HIP + Metal** | AMD, Apple | yes | two sources to keep in step, and HIP drags ROCm in as a user install |
| **SYCL / Kokkos** | broad | yes | heavy runtime riding in the wheel |

### "Work in progress" checked rather than believed

Slang's docs mark the Metal target work-in-progress, and Metal is half of
what we can test, so that label decides a lot. It is also just a label. The
answerable question is whether the current release supports what THIS
kernel needs, so it was compiled: slangc 2026.18.2, one probe kernel using
threadgroup shared memory, barriers, a wave reduction for the peak scan,
and an atomic fetch-add for the hierarchical compaction counter.

All four targets compiled, and they lower to native primitives rather than
emulation:

| feature | Metal | SPIR-V | CUDA |
|---|---|---|---|
| shared memory | `threadgroup array<float2,256>` | `Workgroup` storage class | `__shared__` |
| barrier | `threadgroup_barrier(mem_threadgroup)` | `OpControlBarrier` | `__syncthreads()` |
| wave reduction | **`simd_max`** | **`OpGroupNonUniformFMax ... Reduce`** | `_waveMax` / `__ballot_sync` |
| atomic add | `atomic_fetch_add_explicit(..., relaxed)` | atomic op | `atomicAdd` |

The wave reduction is the one that mattered: it is the peak scan, and on
Metal it comes out as `simd_max`, which is what anyone would hand-write.
The atomic is the hierarchical compaction and it is a real relaxed atomic.

So "work in progress" appears to describe graphics-pipeline completeness --
mesh shaders, raytracing acceleration structures, some SV semantics, which
are the gaps the docs actually list -- and not compute. For a library that
only ever issues compute dispatches, the label is close to irrelevant.

This does not prove the generated code is FAST, only that it is the right
constructs. Codegen quality is still a phase-1 measurement. But the risk
has dropped from "Metal may not be viable" to "Metal may need tuning",
which is an ordinary problem.

### What the testable hardware does to the plan

AMD and Apple are the two you can measure on, and between them they cover
both of Slang's interesting cases.

**AMD wants Vulkan, and the wheel constraint independently agrees.** HIP
would mean ROCm installed on the user's machine, which is exactly the extra
install this cannot have. A Vulkan driver is already there -- AMD's own on
Windows, Mesa RADV on Linux -- and Vulkan is Slang's most mature target.
Constraint and hardware point the same way, so AMD is the low-risk half.

**Apple is the half worth watching, though less than it looked.** Metal is
the only first-class compute path: OpenCL is deprecated and there is no
Vulkan driver. The alternatives to Slang's MSL are SPIR-V through MoltenVK,
which adds a vendored dylib and a translation layer, or a hand-written
Metal kernel. Given that the probe emits native `simd_max` and native
atomics, Slang's own MSL is now the first thing to measure rather than the
fallback.

**Decided: Slang.** The device layer stays an interface with one
implementation per backend, so a disappointing Metal result costs one
kernel rather than the plan -- but that is insurance now, not an expected
path. The one thing that would reopen the decision is phase 1 finding the
generated code materially slower than hand-written MSL or GLSL; codegen
quality is the only question the probe could not answer.

**What is NOT Slang: the CPU path.** Its CPU target exists and will not
match hand-tuned Highway. The existing kernels do not change. That means
two kernel sources rather than one, and that is the honest price of not
regressing the thing that already works.

## The hierarchical filter is the hard part

The flat filter is a straightforward port. The hierarchical one is not, and
it is worth being explicit about why, because it is the piece most likely
to be underestimated.

The decision to reconstruct is **per pair and data-dependent**. On a CPU
that is a branch. On a GPU it is divergence: a workgroup where one pair in
thirty-two escalates pays for the full correlation anyway, and the entire
speedup is gone.

The known shape of the fix is two dispatches and a compaction:

1. coarse pass over all pairs, writing a flag and a coarse peak per pair
2. stream-compact the escalated pairs into a dense work list, with an
   atomic counter for the length
3. indirect dispatch of the reconstruction over exactly that list

This is a well-trodden pattern, but it changes the cost model completely.
On the CPU the cost of escalation is roughly linear in the escalation rate.
On a GPU it is a step function in the number of workgroups the compacted
list fills, plus a fixed cost for the compaction itself that is paid even
when nothing escalates. **The GPU cost table therefore cannot be the CPU
cost table with different numbers in it** -- the shape of the function is
different, and `choose_config` will need a device-aware cost model, not
just device-specific rows.

That is a design question to settle by measurement before any of the
tuning work, because it determines what the table is keyed on.

## The tables across devices

The hierarchical algorithm is the same algorithm on a GPU -- same
decimation, same coarse threshold, same taps, same margin. Nothing in the
dismissal rate is architecture-dependent, so **the accuracy table should
transfer and the cost table certainly does not**.

That asymmetry is worth more than it first looks. The accuracy table is the
expensive one: hours to generate, 13,856 rows, and the low-B_eff extension
alone was 95 minutes. The cost table is the cheap one, about 40 minutes.
If accuracy transfers, **adding a backend costs a cost table**, which is
the difference between a device port being a day and being a week.

Transfer is a hypothesis with a cheap test, so it gets tested rather than
assumed: run the existing `measure()` harness against the GPU backend and
compare dismissal cell by cell against the shipped rows. Agreement within
the trials resolution means one accuracy table for every device. Two things
could break it and both are worth looking for specifically -- different
FMA contraction changing decisions for pairs sitting exactly at the coarse
threshold, and any difference in which sample wins a tie in the peak
reduction.

The cost table needs more than new numbers, because the *shape* of the cost
function changes. Escalation on a CPU costs roughly linearly in the
escalation rate. On a GPU it is a step function in how many workgroups the
compacted list fills, plus a fixed compaction cost paid even when nothing
escalates. `choose_config` will need a device-aware cost model rather than
device-specific rows in the same model.

## Chunking, and why it is its own phase

How the D x T batch is tiled has never been carefully examined -- not on
the GPU, where nothing exists yet, and not on the CPU either. On a GPU it
is the dominant performance parameter, and the roofline says so
quantitatively.

Measured on the Radeon 8060S (gfx1151, 40 CUs, RDNA 3.5), while the CPU was
busy, so these are a floor and not a ceiling:

    bandwidth   186.8 GB/s
    fp32 FMA   5426.8 GFLOP/s
    ridge          29 FLOP/byte

For D=16, T=512, n=4096 -- 2.21 GFLOP of real work -- the tiling alone
moves the workload across that ridge:

    tiling                        traffic   FLOP/byte   bound      time
    perfect reuse                   17 MB       128.0   compute   0.41 ms
    8 data x 32 templates           42 MB        52.8   compute   0.41 ms
    4 data x 16 templates           84 MB        26.4   memory    0.45 ms
    1 data x 8 templates           302 MB         7.3   memory    1.62 ms
    no reuse                       537 MB         4.1   memory    2.87 ms

Seven times between the best and worst tiling, and the cliff sits between
8x32 and 4x16 -- squarely inside the range of tile sizes a shared-memory
budget actually permits. That is not a threshold anyone should guess at.

Two things follow. The fusion argument is confirmed quantitatively: not
writing D x T x n is what puts this workload at 128 FLOP/byte instead of
7.8, and the difference is compute-bound against memory-bound. And the
tiling has to be chosen per (n, D, T, device), which means it is another
measured table, or another axis on the cost table.

**Sequenced after a working GPU path, and covering both CPU and GPU.**
There is no point optimising a tiling before there is something to measure
it on, and the question is shared: the CPU's four-step split already tiles
a transform against cache, and the GPU tiles it against shared memory. They
are the same question asked of different memories, and answering it twice
independently would be the usual way to get two different answers.

## Correctness, and how it gets tested without GPU runners

The existing suites are the asset here: 134 tests, an adversarial set, an
independent reimplementation set, and a precision harness that already
compares against a float64 reference across injected SNR. **The GPU backend
passes the same tests**, which is a far stronger starting position than
writing GPU tests from scratch.

Two things will differ and need deciding up front rather than discovering:

- **Bit-exactness across devices is not achievable** and should not be
  promised. FMA contraction and reduction order differ. The guarantee that
  can hold is the one the hierarchical filter already makes -- the peaks
  reported are the peaks the flat filter of the *same* device would report,
  exactly -- plus a stated tolerance between devices. The precision page
  grows a per-device column.
- **The accuracy table may transfer and the cost table certainly does not.**
  Dismissal is a property of the algorithm; if the GPU runs the same
  algorithm it should measure the same rates, and that is a hypothesis to
  test cheaply and early, not to assume. Cost is a property of the machine.

For CI: GitHub's hosted runners have no GPUs, and self-hosted runners for a
library like this are a maintenance burden. **Lavapipe -- a software Vulkan
implementation -- runs the SPIR-V path on an ordinary runner.** It is far
too slow to benchmark and entirely adequate to prove correctness, which
means every push can still check that the GPU kernels compute the right
answer. Performance is measured on real hardware, deliberately and
occasionally, the way the tuning tables already are.

## Getting data onto the device

Peak-only output means the *return* trip is tiny, which is the whole point.
The input is the problem: uploading D segments per call would dominate
everything.

The library takes spectra, so a caller running on a GPU already has them
there. Accepting device buffers directly -- via `__cuda_array_interface__`
and DLPack, both of which are protocols rather than dependencies -- lets a
cupy or torch user hand over a pointer with no round trip. Host arrays keep
working and upload as they do now.

`run_series`, which already exists to remove per-block round trips, matters
much more on a device than it does on a CPU.

## Order of work

Each phase ends with something measurable, and the early ones are cheap
enough to abandon.

**0. Decide the contract.** What "the same answer" means across devices;
what the device-aware cost model is keyed on. Writing, not code, and it
gates the rest.

**1. Spike the two riskiest assumptions, on the two machines you have.**
One fused kernel, one transform length, correctness against the float64
reference, built from one Slang source and run on **both** AMD via Vulkan
and Apple via Metal.

Two questions, and the phase is not finished until both have numbers:

- *Does the fusion pay?* Compare against the honest alternative -- a vendor
  FFT plus a separate reduction -- not against the CPU. If fusing does not
  beat that by a clear margin, the bespoke kernel is not justified and the
  rest of this plan is wrong. Better to learn that in a week.
- *How fast is Slang's Metal?* The probe settled that it emits the right
  constructs -- `simd_max`, real threadgroup memory, real atomics. What it
  cannot settle is codegen quality, so this still needs a hand-written MSL
  kernel once, on purpose, to compare against.

Doing Apple in phase 1 rather than phase 6 inverts the usual order
deliberately. The risk is concentrated there, and it is testable now.

**2. Build and packaging.** AOT compilation in CI, embedded blobs, runtime
`dlopen`, the device axis on `targets()`/`backend()`, and a wheel that still
installs and passes on a machine with no GPU at all. Deliberately early:
the wheel constraint is the one most likely to invalidate a design, and
finding that out after the kernels are written is the expensive order.

**3. The flat filter, complete.** All eleven lengths, the peak scan, the
windowing and binning semantics, passing the existing suites on lavapipe
and on real hardware.

**4. The hierarchical filter.** Compaction and indirect dispatch, and the
measurement that settles what the GPU cost model looks like.

**5. Tuning on device, and chunking for both.** First test whether the
accuracy table transfers, because it decides how expensive every later
backend is. Then the device cost table, the device-aware cost model the
compaction forces, and the chunking question above -- for the CPU at the
same time, since it is one question about two memories.

**6. CUDA.** The backend nobody here can test, added last and on purpose:
by this point the interface has survived two real implementations, so NVIDIA
is an exercise in the authoring layer rather than a discovery. If Slang has
paid for itself this phase is cheap, and if it has not, that will already
be obvious from phases 1 and 4.

## What would make me change this plan

- The phase-1 spike shows fusion does not beat cuFFT-plus-a-reduction by
  enough to justify a bespoke kernel.
- Slang's Metal output is materially worse than hand-written MSL for this
  kernel shape. That does not kill Slang -- it demotes it to Vulkan and
  CUDA, with Apple hand-written behind the same interface.
- Slang's SPIR-V is materially worse than hand-written GLSL on AMD. That
  would kill it, because Vulkan is the target it is best at, and being
  beaten there means the abstraction costs more than it saves.
- The compaction overhead in phase 4 turns out to dominate at realistic
  escalation rates, which would mean the hierarchical mode is a CPU feature
  and the GPU ships the flat filter only. That would be a perfectly good
  outcome to discover early.
