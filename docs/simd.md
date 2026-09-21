# The SIMD layer

The kernel is written once, against the `V_*` macros in `src/simd-inl.h`,
which bind to [Google Highway](https://github.com/google/highway). Highway
lowers each operation to the target's intrinsics.

## How a build decides what it contains

`src/kernel.cc` includes `hwy/foreach_target.h`, so the compiler emits one
copy of the kernel per SIMD target it can generate for the architecture being
built, each with its own target attributes and its own vector width.
`HWY_DYNAMIC_DISPATCH` selects one at first use from what the CPU reports.

Nothing in the build names a target. `AP_W` is
`HWY_MAX_LANES_D(CappedTag<float, 16>)`, so it follows whatever the current
pass is compiling for, and the kernel headers use Highway's `-inl.h`
convention: a plain include guard would let only the first pass define
anything.

On a current x86-64 build that gives AVX3 (16 lanes), AVX2 (8) and SSE4 (4).
`setup.py` disables the rest -- SVE and RVV because sizeless vectors cannot be
array members and the kernel holds `vf TR[AP_W]`, SCALAR because one lane is
below what the layout assumes, and the AVX-512 variants past AVX3 because
nothing has measured a reason for them.

```python
import matchedfilter as mf
mf.targets()       # ('AVX3', 'AVX2', 'SSE4') -- in this build, on this CPU
mf.backend()       # 'AVX3'
mf.set_target('AVX2')   # for comparing; None restores the default
```

`MF_ISA` does the same from the environment.

## Measured

One machine (Zen 5), one process, on the hierarchical workload pycbc's ratio
filter drives: a 2^20 reference series in overlap-save blocks against 64
templates at n=4096.

| target | lanes | ms/segment | relative |
|---|---:|---:|---:|
| AVX3 | 16 | 10.2 | 1.00 |
| AVX2 | 8 | 10.6 | 1.04 |
| SSE4 | 4 | 20.1 | 1.97 |

Against the hand-written AVX2 intrinsics this replaced, at the same width and
paired over 15 interleaved rounds: **0.96x**, output identical, reproduced
twice. On AVX-512 Highway
is about 23% behind the intrinsic kernel that was removed, which is a
deliberate trade -- that path was roughly 500 lines serving hardware most runs
will not have.

Peaks agree across targets to 2.7e-7 relative, and about one bin in 3000 picks
the other side of a tie. That is fp32 summation order, not disagreement: the
four-step transform sums in a different order at each width.

A branch in the stage-A tail selecting between two twiddle representations was
worth about 4% on AVX2 on its own, and closed most of the AVX2-to-AVX3 gap.
The representation it selected had been measured slower and was never enabled;
what cost the time was the branch being there at all.

## Two things that were not obvious

**The transpose is the whole margin.** Storing each vector to a scalar array
and regathering the columns is correct and reads clearly, and the compiler
expanded it into 960 shuffle instructions against the intrinsics' 386. The
same mistake had been made before in a compiler-vectorised back end, where it
cost nothing measurable. What a scalar gather costs depends entirely on what
surrounds it.

`src/simd-inl.h` carries a generic interleave network for every width, plus
one specialisation for AVX2. The generic network is correct on AVX2 too and
costs 12% there: a whole-vector interleave crosses 128-bit lanes and needs
`vpermps`, while `InterleaveLower` is one `vunpcklps`. On AVX-512 the whole
interleave is a single `vpermt2ps` and the generic network wins. It is a
property of the hardware rather than a shortcut.

**`inline` is a hint.** Under Highway's target pragma, one helper stopped
being inlined and the kernel lost its parity; `always_inline` restored it. The
evidence pointed at a call boundary for some time before that was believed.
