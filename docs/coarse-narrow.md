# A narrower coarse pass

The coarse pass is 84% of the hierarchical filter's time at the operating
point that misses no triggers. It answers one question -- is anything in this
lag window above the gate -- and that question tolerates arithmetic the
reconstruction could not.

This is the plan for exploiting that, and the measurements it rests on. All
figures come from captured `pycbc_inspiral_fir` calls, not synthetic data.

## What makes it safe

Correctness here is structural, not statistical.

Quantisation makes the coarse statistic read slightly low or slightly high.
Multiply it by its own worst-case under-report before comparing to the gate
and it can no longer read low at all, so **no trigger can be lost at any
width**. The entire error budget turns into trigger rate, and trigger rate is
cheap: reconstruction is 16% of the time at the operating point, so paying for
a few more reconstructions buys a lot of coarse-pass speed.

Measured over 520 real pairs, gate placed where the true statistic gives a 5%
trigger rate:

| bits | worst under-report | bias | unsafe flips | reconstructions |
|---:|---:|---:|---:|---|
| 16 | 0.9999 | 1.0001 | 0 | +0% |
| 12 | 0.9990 | 1.0010 | 0 | +0% |
| 10 | 0.9959 | 1.0041 | 0 | +15% |
| 8 | 0.9837 | 1.0166 | 0 | +23% |
| 6 | 0.9506 | 1.0519 | 0 | +92% |
| 4 | 0.8375 | 1.1940 | 0 | +415% |

int8 is the knee: 2x the lanes of int16, 4x of float, for 23% more
reconstructions.

## Two things that do not work

**Saturating inside the transform.** Putting the fixed-point scale where the
decision is -- gate high in the range, louder values clipping -- sounds right
and is wrong. The transform is linear and every intermediate contributes to
the peak, so a clipped intermediate does not mean "loud", it means the peak
comes out wrong. Measured against block floating point at the same widths:

| bits | block float | gate-fixed + saturate |
|---:|---|---|
| 8 | +23% reconstructions | +177% |
| 6 | +92% | +1100% |
| 4 | +415% | +1896%, worst case 0.0019 |

Saturation is safe only at the final magnitude compare. Block floating point
stays.

**SWAR packing of two values per lane.** Packing relies on the product fitting
inside its field. Eight-bit data times an eight-bit twiddle needs sixteen bits
of product, so the fields must be sixteen bits, which is exactly using int16
lanes with extra steps. Packed *adds* do work and would save about a quarter
of the add/sub traffic, but the butterfly is multiply-dominated.

## The primitives

The gain from int8 is not the lane count alone. A complex multiply is a
two-term dot product in each component, which these instructions compute
directly. All are exposed by Highway and present on this CPU.

| Highway | instruction | shape | complex multiply |
|---|---|---|---|
| `MulFixedPoint15` | `vpmulhrsw` | i16xi16 -> i16 | 4 mul + 2 add/sub = 6 |
| `ReorderWidenMulAccumulate` | `vpmaddwd` | i16xi16 -> i32, 2-term | 2 |
| `SatWidenMulPairwiseAdd` | `vpmaddubsw` | u8xi8 -> i16, 2-term | 2, at 2x lanes |
| `SumOfMulQuadAccumulate` | `vpdpbusd` | u8xi8 -> i32, 4-term | radix-4 in 4 |

`(a+ib)(c+id)`: with `[a,b]` adjacent and the twiddle as `[c,-d]`, one
pairwise-dot gives `ac-bd`; with `[d,c]` it gives `ad+bc`. Both components in
two instructions instead of six, on twice the lanes.

The catch is that these want operands interleaved and produce results split,
while the kernel is split throughout. Whether the repacking eats the gain is
the open question, and it is what Phase 1 measures rather than assumes.

## What int16 alone is worth

Measured, because it bounds what any of this can achieve. The same four-step
structure written in both types, at the coarse size:

| | int16 vs float | absolute vs the tuned float kernel |
|---|---:|---|
| isolated butterfly loop | 2.01x | -- |
| FFT-shaped loop | 2.1-2.9x | -- |
| four-step, the real structure | **1.2-1.4x** | my float is 1.7x off tuned |
| lane-per-template, no shuffles | 2.05x | 6x off tuned, memory bound |

The type gain is real but only materialises where shuffles are absent, and the
structure with no shuffles loses far more to cache behaviour than it gains.
In the structure that wins, transposes, twiddle loads and the max scan do not
halve with the element type, which is why int16 lands at 1.3x rather than 2x.

## Phase 1 result: no-go

Measured. Each kernel does one radix-2 twiddle butterfly over the same element
count and leaves the result in its own input format, so the repack counts.
Nanoseconds per complex element per level:

| kernel | AVX-512 | vs (1) | AVX2 | vs (1) |
|---|---:|---:|---:|---:|
| 1 split i16 Q15 (`vpmulhrsw`) | 0.0594 | 1.00x | 0.0713 | 1.00x |
| 2 interleaved i16 (`vpmaddwd`) | 0.0824 | 0.72x | 0.1451 | 0.49x |
| 3 interleaved i8 (`vpmaddubsw`) | 0.0499 | 1.19x | 0.0780 | 0.91x |
| 4 i8 radix-4 (`vpdpbusd`) | 0.0361 | 1.64x | 0.1300 | 0.55x |

Nothing clears the 1.5x threshold on both targets, and the reason is not the
repack. With the pack back to the input format removed entirely -- the ceiling
Phase 2 was meant to chase -- the twiddle multiply alone costs:

| | AVX-512 | AVX2 |
|---|---:|---:|
| 1 split i16 Q15 | 0.0232 | 0.0378 |
| 3 interleaved i8 | 0.0430 (**0.54x**) | 0.0588 (**0.64x**) |

int8 is slower than int16 on the arithmetic by itself, in a comparison where
both kernels do the same work in the same structure and neither packs back.
The instruction-count argument was right and did not matter.

Why it does not matter is not established here. Attempts to measure the issue
rate of these instructions in isolation produced numbers that contradict each
other across targets, so the mechanism is inferred rather than shown: most
likely `vpmaddubsw`, which performs two multiplies, an add and a saturation
per output lane, does not issue fast enough for two of them to beat four
`vpmulhrsw`. What is measured is the outcome, not the cause.

The generalisation is worth keeping: these instructions are built for dense
matrix products, where every output needs every input times a distinct
coefficient. An FFT is the opposite -- its twiddles are sparse, structured and
mostly trivial. Kernel 4 flatters itself for exactly this reason, computing a
dense four-term dot where a real radix-4 butterfly needs three twiddle
multiplies and some sign flips; on AVX2, where it cannot hide the twiddle
traffic, it drops to 0.55x.

So the narrow-arithmetic route caps out at int16's measured 1.2-1.4x in the
real structure, about 1.25x overall. Not worth a second kernel.

## The plan that was tested

**Phase 1 -- primitive economics.** Microbenchmark four inner kernels at equal
element counts, each *including* the repack back to its own input format,
since that is the real cost:

1. split i16 Q15 (`MulFixedPoint15`) -- the baseline, 1.3x over float
2. interleaved i16 (`vpmaddwd`) + narrow + re-interleave
3. interleaved i8 (`vpmaddubsw`) + narrow + re-interleave
4. i8 radix-4 (`vpdpbusd`) + narrow + regroup

Report ns/element and, from the disassembly, instructions/element split into
arithmetic and shuffle. Go/no-go: does any beat (1) by 1.5x including repack?

**Phase 2 -- make the repack free.** Only if the winner is repack-dominated.
The four-step already moves the intermediate through memory between stage A
and stage B, so narrowing on store and widening on load rides along with
traffic that exists rather than adding a pass. Inside a codelet, which is
register-resident, keep the wide form and never repack. Radix-4 codelets halve
the number of format boundaries per transform.

**Phase 3 -- precision hierarchy.** This is where "resolution where it
matters" actually pays, since it cannot pay inside the butterfly. An int8
reject pass with the upward bias, then the existing pass only on survivors. At
a 1% trigger gate int8 passes 6.2% of pairs, so the cost model is
`0.5C + 0.06C = 0.56C` against `C` for int16 alone -- and unsafe flips stay at
zero by construction, so the fixtures should show 842/842 unchanged.

**Phase 4 -- integrate**, with `tools/hier_all.sh` as the gate: 12 captured
segments, 842 triggers, zero missed, and the ms/segment must fall.

Phases 2 to 4 were not run: Phase 1's ceiling measurement removed their
premise.

## Why banking the rearrangement does not rescue it

In an N templates by M data batch, anything that can be rearranged once is
free against N*M pair transforms, and the library already leans on that: the
template and data spectra are stored group-major at ingest so every pair
transform reads sequentially, which is the whole reason preprocessing being
free matters.

That principle does not apply to the cost measured here. The format churn is
not at ingest, it is **per butterfly stage**: the dot-product instructions
consume interleaved operands and produce split results, so every stage inside
the transform has to put its output back into the form the next stage's
multiply wants. The data being transformed is the product, which is per-pair,
so nothing about it can be banked.

Seen that way the current representation is already the answer to the
question. `vpmulhrsw` takes split and produces split, so the kernel never
changes format at all, from ingest to the final magnitude. Any scheme that
buys cheaper arithmetic by demanding a different operand layout has to pay for
that layout once per stage, ten times per transform, on data that is unique to
the pair.

## What survives

The safety argument. Biasing the coarse statistic up by its worst-case
under-report makes lost triggers impossible at any width, and that is worth
keeping whatever the arithmetic ends up being -- it converts a correctness
risk into a trigger-rate cost, which is the cheap axis here.

The precision hierarchy in Phase 3 is also untouched by this result, since it
does not depend on narrow arithmetic being fast: a cheap reject pass followed
by an accurate one works with any two representations, including two float
ones at different transform sizes. That is the same idea as the existing
even/odd split and would have to be justified against it.
