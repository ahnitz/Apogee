# Using matchedfilter

What goes in, what comes back, and how the hierarchical mode is driven.

Every example below is executed when this page is built, and the block
underneath it is what it printed. None of it is transcribed. That matters
more than it sounds: the page this replaced carried a hand-written table
claiming 31x over numpy, which turned out to be measuring Python loop
overhead in double precision, and it sat there until a reader questioned it.
Run them yourself with `python -m matchedfilter.tutorial`.

Measured performance lives on the benchmark pages, not here.

## Install

```bash
pip install matchedfilter
```

Every release so far is an alpha, and pip installs a pre-release when that is
all a project has. Once a stable version exists, getting an alpha will need
`pip install --pre matchedfilter`.

Wheels are built for CPython 3.9 to 3.14 on Linux x86-64 (manylinux and
musllinux) and macOS arm64. Anywhere else pip falls back to the source
distribution, which needs numpy and a C compiler -- including Linux arm64,
where it builds and passes but no wheel is published yet.

## Inputs and outputs

Inputs are **frequency domain**: the unnormalised forward transform of each
segment, in natural order. Produce them with whatever you already use (numpy,
MKL, FFTW); matchedfilter does not own that step. Everything is
**complex64**, and there is no double-precision path.

`ndata` and `ntemplates` are declared to the constructor rather than inferred
from the first call, because the plan, the twiddles and the working buffers
all depend on them. Declaring them once lets plans reuse storage. First-use GPU dispatches and
adaptive CPU layouts can still allocate.

[[example:A complete example]]

With unit-norm templates and unit-variance noise, `abs(peak["value"])` reads
directly as a signal-to-noise ratio, which is why the examples are built that
way.  A peak is `index` and `value` only: the magnitude was a third field once
and equalled `abs(value)` exactly, so it carried no information and cost a copy
on every call.

[[example:What comes back]]

## Bounding the output

`binsize` sets how many lags share one reported peak. One record per bin, so
`binsize=n` gives a single peak per pair and `binsize=1024` gives `n/1024`.

[[example:One peak per window]]

A bin whose peak did not exceed the threshold still occupies its slot, with
`index == -1`, so `peaks[d, t, j]` is bin `j` without searching.

[[example:Thresholding]]

`window=(start, end)` bounds which lags are searched at all. An overlap-save
caller should use it: the wrap-around region of each block is invalid, and
searching it is not free -- particularly in the hierarchical mode, where
every extra lag is another chance for noise to force a reconstruction.

[[example:Bounding the lags searched]]

`run_series` takes a whole time series plus the block layout (`starts`,
`win_start`, `win_end`) and executes it in one call, which removes the
per-block round trip and lets the library group blocks internally.

## One thing to watch

[[example:The output buffer is reused]]

## The hierarchical mode

`HierarchicalFilter` runs a cheap decimated pass first and only reconstructs
the full correlation where that pass could not rule a peak out. It reports
the same peaks as the flat filter, minus a controlled fraction it is allowed
to miss: `fd` is that budget, and `snr` is the peak strength the budget is
quoted at.

It needs `set_reference(power)`: the expected power of the filter **output**,
bin by bin. Not the template's own power -- the two differ whenever the data
is coloured, and the configuration is chosen from this, so getting it wrong
gets the configuration wrong.

[[example:The hierarchical mode]]

Where the shipped tables have no measurement covering the request, it raises
instead of guessing.

[[example:When it refuses]]

## Choosing a transform length

CPU lengths are powers of two from 64 to 1048576. GPU lengths are
1024, 2048, 4096, 8192 and 16384, subject to device limits. The
hierarchical mode additionally needs measured tuning coverage at that length;
`tools/hmf_tune.py` generates more.

## Running on a GPU

Pass `device=`. The spelling is PyTorch's, because you already know it:

```python
import matchedfilter as mf

mf.devices()
# [Device('cpu:0', 'AMD Ryzen 9 9950X', backend='AVX3'),
#  Device('gpu:0', 'AMD Radeon 8060S', backend='vulkan')]

filt = mf.MatchedFilter(4096, ndata=16, ntemplates=64, device="gpu")
```

`"cpu"`, `"gpu"`, `"gpu:1"` and `"auto"` are all accepted, and `MF_DEVICE`
sets the default from the environment so a benchmark harness can switch
backends without editing the code that builds the plans.

**The default is the CPU even when a GPU is present.** Dispatching somewhere
you did not name would change numerics and failure modes without being asked.
`"auto"` exists for callers who want the library to choose, but they have to
say so.

Both devices return the same fields, the same shapes, and the same
`index == -1` for a bin nothing cleared, so the same code reads either. They
are not bit-identical: the transform sums in a different order, so values
agree to single precision rather than exactly, and an index may differ where
two samples tie.

The GPU path is a Vulkan compute backend. The kernels ship compiled inside
the wheel, so there is no toolchain to install, no second wheel to pick, and
nothing extra to import — but it does need a working Vulkan driver.

Two limits, both of which raise rather than working around you:

- **Transform length 1024 to 16384.** One workgroup carries a whole
  transform; longer ones need more than 1024 threads and are not implemented.
- **At most 2048 bins per call**, that is `ceil((end - start) / binsize)`.
  The per-bin table shares the kernel's 8 KB of workgroup memory, and
  enlarging it would halve occupancy.

A GPU that reports no devices on a machine that has one is usually a
shadowed C++ runtime rather than a driver problem — `matchedfilter` says so
in the error. See [the GPU notes](notes.html) for that and the rest.

## Current capabilities

The GPU backend is newer than the CPU one and deliberately covers less. What
it does cover it holds to the same tests; where it does not, it refuses
rather than falling back silently, so nothing is answered by a path you did
not ask for.

| | CPU | GPU |
|---|---|---|
| transform lengths | 1024 – 1048576 | **1024 – 16384** |
| flat filter | yes | yes |
| hierarchical filter | yes | yes |
| `run_series` | yes | yes |
| `binsize`, `window`, `threshold` | arbitrary | arbitrary |
| bins per call | unlimited | unlimited (split internally past 2048) |
| precision | float32 | float32 |
| parallelism | single-threaded by design | the device |

Why 16384 on the GPU: one workgroup carries a whole transform, and at
`n/16` threads per workgroup 16384 is what 1024 threads reach. Longer
transforms need the decomposition split across dispatches, which is not
written. Asking for one raises, naming the sizes that work.

Shared CPU/GPU allocations are available through `filter.empty_shared()`.
For zero-copy bank binding, DLPack interoperability, and the remaining
device/stream limits, see [GPU forward FFT and shared arrays](gpu-forward-and-arrays.md).

Other things worth knowing, all work in progress:

- **Input must be host-resident.** Arrays are accepted over DLPack from any
  library, but an array already on an accelerator is refused rather than
  copied down and back — see *Running on a GPU* above.
- **The hierarchical mode escalates its interpolation window** instead of
  interpolating it. That is strictly more conservative — it can only refine
  pairs the CPU would have dismissed, never the reverse — and costs about
  1–2% more escalation.
- **Per-device tuning is measured on one device.** The kernel's shared-memory
  staging was tuned on a Radeon 8060S; other devices will run correctly but
  not necessarily at their best until they have their own measurements.
- **No float64 path**, on either device, and none planned.

### Which GPUs

Two backends, one API. On Linux and Windows it is Vulkan: the kernels ship
as SPIR-V and the runtime loads whatever driver the system provides, so
AMD, NVIDIA and Intel all work from the same wheel with nothing to install.
On macOS it is Metal, chosen automatically — `device="gpu"` does not need
to be told which. MoltenVK is not bundled and is not needed.

Both backends are generated from the same Slang source, so they are the
same kernel rather than two implementations to keep in step. The wheel
carries compiled `.metallib` files; if one is missing or stale the runtime
compiles the shipped `.metal` source instead rather than refusing.

**macOS status.** The whole suite passes on an Apple M2 — 367 passed, 0
failed — and the GPU agrees with the CPU index for index. Two limits, and
the second is stricter than CI alone would tell you:

- Apple caps threadgroup memory at 32 KB and the fastest builds here use
  64 KB, so the two largest sizes fall back to a 32 KB build. Measured on
  gfx1151, where both builds run: the 32 KB one is 1.11x slower at n=8192
  and 1.29x at n=16384. Halving the staging doubles the exchange chunks
  and their barriers, and that costs more than the occupancy it buys — so
  this is a real penalty at those two sizes, not a formality.
- **Every supported length runs** — n=1024 through 16384, verified against
  the CPU index-for-index on an Apple M2, flat and hierarchical.

  It nearly did not. How many threads a device allows depends on the
  compiled kernel's register use, not only on the hardware, and it is asked
  per pipeline. Left alone, Apple's compiler optimises for occupancy and
  stops wherever the registers land — 576 for the n=16384 kernel against
  the 1024 it is dispatched at, so that length was refused outright. Asked
  for 1024 via `MTLComputePipelineDescriptor` it delivers 1024.

  The library asks only when the default is short. Declaring the size
  unconditionally also builds every pipeline, and it *changed the answer* at
  n=4096, where the default already allowed 448 and nothing needed asking.

A software rasteriser will not catch a mistake here. llvmpipe reports 32 KB
and then runs a 64 KB kernel regardless, so the lavapipe CI path passes
where real hardware would fail to create the pipeline.

## Platforms

One kernel source is compiled once per SIMD target the compiler can generate,
and the target is chosen at run time from what the CPU reports. On x86-64
that is AVX3, AVX2 and SSE4; on arm64 it is NEON.

| platform | tested |
|---|---|
| Linux x86-64 | every push |
| Linux arm64 | every push |
| macOS arm64 | every push |
| macOS x86-64 | no |

macOS on Intel is untested rather than known-broken: hosted runners for it
are being retired, so nothing measures it. `matchedfilter.targets()` lists
what a build holds that the CPU can run, `matchedfilter.backend()` reports
which one was selected, and `set_target()` or `MF_ISA` forces one.

## CPU/GPU parity and lifecycle

See the [parity audit](cpu-gpu-parity.md) for tested features and limits.
Initialize every data/template row you request. After `run_series`, call
`set_data` before a subsequent `run`; series execution uses internal data
slots. Use setters again after changing caller-owned inputs. Copy results
that must survive subsequent calls.
