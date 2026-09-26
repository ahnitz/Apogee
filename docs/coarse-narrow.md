# A narrower coarse pass

The coarse pass is 84% of the hierarchical filter's time at the operating
point that misses no triggers. It answers one question -- is anything in this
lag window above the coarse threshold -- and that question tolerates arithmetic the
reconstruction could not.

This is the plan for exploiting that, and the measurements it rests on. All
figures come from captured `pycbc_inspiral_fir` calls, not synthetic data.

## What makes it safe

Correctness here is structural, not statistical.

Quantisation makes the coarse statistic read slightly low or slightly high.
Multiply it by its own worst-case under-report before comparing to the coarse threshold
and it can no longer read low at all, so **no trigger can be lost at any
width**. The entire error budget turns into trigger rate.

**The "trigger rate is cheap" premise below is STALE and it is the load
bearing one.** It said reconstruction is 16% of the time at the operating
point. Measured with MF_HMF_PROF across the configurations selection
actually picks, reconstruction is 41% to 73%, and only reaches single
digits at band 1024 with a 0.6% escalation rate:

    snr 5.5 band  512   coarse 58%   refine 41%
    snr 6.5 band  256   coarse 44%   refine 55%
    snr 5.0 band 1024   coarse 73%   refine 27%
    snr 6.0 band  256   coarse 26%   refine 73%
    snr 6.0 band 1024   coarse 95%   refine  5%

So extra reconstructions are not cheap at the operating point, they are the
larger half of it. Any variant that trades accuracy for trigger rate --
including the "+23% reconstructions" int8-as-primary row in the table below
-- costs 0.23 x 0.55 = +13% of total time where this doc assumed
0.23 x 0.16 = +4%.

**But it cuts the other way for phase 3, and a first pass at this correction
got that backwards.** Phase 3 is an int8 REJECT pass with an upward bias,
which creates no extra reconstructions by construction. Its saving is
confined to the coarse stage, so its end-to-end payoff is pure Amdahl on the
coarse share, and the measured share is much larger than 84%-of-nothing this
doc assumed:

    coarse share   0.56C coarse cost -> end to end
      0.26   (snr 6.0 band 256)          1.13x
      0.44   (snr 6.5 band 256)          1.24x
      0.58   (snr 5.5 band 512)          1.34x
      0.73   (snr 5.0 band 1024)         1.47x

So the stale 16% flattered every variant that spends trigger rate and
understated the one that does not. Phase 3 is the better bet of the two by
more than the doc suggests, not less.

Measured over 520 real pairs, margin placed where the true statistic gives a 5%
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
decision is -- margin high in the range, louder values clipping -- sounds right
and is wrong. The transform is linear and every intermediate contributes to
the peak, so a clipped intermediate does not mean "loud", it means the peak
comes out wrong. Measured against block floating point at the same widths:

| bits | block float | margin-fixed + saturate |
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
a 1% trigger margin int8 passes 6.2% of pairs, so the cost model is
`0.5C + 0.06C = 0.56C` against `C` for int16 alone -- and unsafe flips stay at
zero by construction, so the fixtures should show 842/842 unchanged.

**Phase 4 -- integrate**, with `tools/hier_all.sh` as the coarse threshold: 12 captured
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

## Settled: the two-minute experiment nobody ran

Everything above argues about int16 from isolated kernels, and lands on
"1.2-1.4x in the real structure, about 1.25x overall". The premise underneath
all of it is that int16 is worth something because it doubles the lanes. That
premise is directly testable in the real fused kernel on the real workload, by
asking what the LAST doubling of lanes bought.

Controlled -- same ISA (AVX-512), same build, only `AP_W` varying, three reps,
even coarse pass at band 1024 in TSC ticks per pair:

| `AP_W` | ticks/pair |
|---|---|
| 8 | 2032, 2055, 2044 |
| 16 | 2020, 2026, 2151 |

Halving the vector width costs nothing. Across ISAs the same thing shows with
the saturation visible: SSE4 (4 lanes) 4677, AVX2 (8) 2274, AVX-512 (16) 2017 --
2.06x for the first doubling and 1.13x for the second.

So the even pass is already width-insensitive at 16 lanes. Doubling again to 32
int16 lanes buys nothing, and would make the corner turn worse, since the
transpose becomes 32x32 instead of 16x16. Blocking knobs (`MF_GBLK`, `MF_BBLK`)
move it by nothing either, and the four-step factorisation for m=1024 is already
at its optimum (32x32 = 2013-2048 ticks, against 2260 at 16 and 2301 at 64).

Precision was never the obstacle, which is worth stating because it is where
the effort naturally goes. Modelled end to end on 456 real captured pairs --
data and template each quantised to Q15, product formed exactly in int32 and
renormalised by one shift, then a Q15 transform with an unconditional `>>1` per
stage and no block-floating-point reduction at all -- the error band on the
coarse maximum is **1.0125x**, against a margin that sits 1.19x above the median.
Zero saturation. `tools/coarse_fixed.py` has the models; the product, not the
transform, carries the error, because a Q15 multiply rounds each partial
product before the subtract and pins the output scale to two operand maxima
that occur at different bins.

The route is closed, and not for a precision reason: int16's entire value is
lane count, and lane count is not what this kernel is short of.

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

## Searching for a replacement instead of designing one

The coarse stage answers one scalar question, so it is fair to ask whether a
cheap program -- found rather than derived -- could answer it. Three
constraints make the space searchable: a single pass over the band product, a
handful of registers, and operations only between the current sample and a
register. Nothing need be linear or sensible; the point is to let a search
exploit whatever the operations do. `tools/stream_search.py` does this, scored
on BRACKET WIDTH (the ratio of largest to smallest truth/prediction), which is
what decides how many pairs a margin settles without the transform.

It does not work, at least not yet, and the interesting part is why.

| approach | flops | bracket width |
|---|---:|---:|
| sum \|P\| (by hand) | 4096 | 1.63 |
| Parseval, sqrt(m*E) (by hand) | 2048 | 1.65 |
| search, 4 registers, 6 instructions | 12288 | 1.690 |
| search, 6 registers, 10 instructions | 20480 | 1.644 |
| interpolation, after the first transform | 2304 | 1.14 |

Anything above about 1.2 settles no pairs at the coarse threshold, which sits only ~1.7x
above a typical maximum. Every search converges to an accumulator over |P| or
|P|^2 -- the energy family -- and cannot beat what that family gives by hand.

Two reasons, one physical and one about the search.

The physical one: a matched filter's output energy is fixed by Parseval and a
weak signal barely moves it. Measured over 2220 real pairs, sqrt(m*E) has a
coefficient of variation of 0.033 against the true maximum's 0.100, and
correlates with it at r = +0.27. The maximum is set by WHERE the phases align,
and energy discards phase entirely. Every statistic cheap enough to consider
either discards phase or aliases it: folding the spectrum by F costs 1/F of the
transform but sums F lags incoherently into each output, diluting a peak by
sqrt(F). That single law explains the band sweep, the fold statistics and the
lag-grid experiments together.

The search reason is that this search is weak, and its negative result should
be read that way. Six thousand hill-climbing steps over a space of maybe 1e20,
no crossover, no population, no seeding. It cannot reach the region worth
exploring: a phasor needs two registers updated jointly with cos and sin
constants, which single-instruction mutation will not assemble, so the search
falls into the basin it can reach. A fair attempt needs batched fitness
evaluation -- every candidate is the same 1024-step loop over different
opcodes, which vectorises across candidates -- a real evolutionary search, and
seeding from known primitives.

Worth noting what the published work does and does not cover. AlphaDev and
STOKE search instruction sequences against a cost model, but both require
exact semantics, which is what lets them use equivalence checking. Searching
for an APPROXIMATE surrogate replaces that with a statistical criterion, which
is a weaker signal over a larger space, and closer to symbolic regression than
to superoptimisation.

## The one number that judges any pre-filter

Any pre-filter, however computed, rejects a pair only when `stat/worst < margin`.
Since `stat >= worst * truth`, that rejects exactly the pairs with
`truth < worst * margin`. So the rejection fraction depends on a single property
of the statistic -- its worst-case recovery -- and on the distribution of the
true coarse maximum. Measured over 2052 real pairs, that maximum has a
coefficient of variation of **0.103**, so the coarse threshold sits only **1.19x** above
the median. The resulting curve:

| worst-case recovery | rejects at the 5% margin | at the 1% margin |
|---:|---:|---:|
| 0.70 | 1.2% | 9.3% |
| 0.80 | 26.4% | 62.7% |
| 0.85 | 53.3% | 81.3% |
| 0.90 | 75.3% | 92.1% |
| 0.95 | 88.2% | 96.9% |

There is a cliff between 0.70 and 0.85. A statistic pays for itself when the
fraction it rejects exceeds its cost, so the design target is:

> **worst-case recovery above ~0.85, at a cost below the rejection it buys.**

Everything measured falls into place against it:

| statistic | cost | worst | rejects | |
|---|---:|---:|---:|---|
| Parseval, L1, any cheap feature | 0.04 | ~0.1 | 0% | dead |
| lag decimation F=8 | 0.13 | 0.39 | 0.6% | dead |
| lag decimation F=2 | 0.49 | 0.67 | 4.5% | dead |
| multi-offset F=4 x2 | 0.48 | 0.65 | 1.7% | dead |
| semi-coherent stack F=2 | 0.94 | 0.97 | ~90% | costs too much |
| interpolation from the even pass | 0.045 | 0.93-0.97 | 85-91% | ~6x |

Nothing that decimates lags or narrows the band clears 0.85 -- every variant
lands between 0.24 and 0.67, because both devices trade resolution for cost
and the cliff is steep. Only a statistic with full lag resolution clears it,
which is why interpolating from an already-computed transform is the one thing
that has worked.

## What the literature says about this shape of problem

- **Filter-and-refine with a contractive bound.** The GEMINI framework
  formalises exactly this: reduce dimensionality, bound the true distance from
  below, and no candidate is ever falsely dismissed. Its canonical instance --
  keep the first few DFT coefficients and bound the Euclidean distance by
  Parseval -- is band-limiting, which is what the coarse pass does; the
  recovery factors are the contraction constant. Standard practice there is to
  **cascade several bounds** of increasing tightness and cost, where this
  filter has only one.
- **Hierarchical matched filtering** in gravitational-wave searches (Mohanty
  and Dhurandhar, and the modern subsolar-mass work) builds its hierarchy over
  *template spacing*. This one builds it over *frequency and lag resolution*.
  The two axes are independent and could compose.
- **Semi-coherent searches** and their N^(1/4) sensitivity law are the same
  trade, with a better exponent because they stack powers rather than complex
  amplitudes. Measured here: worst case improves from 0.60 to 0.97, but the
  cost goes from 0.49 to 0.94, so at equal cost plain decimation still wins.
- **Sparse FFT** is the closest relative -- sublinear recovery of the largest
  Fourier coefficients by binning into buckets, which is what decimation does.
  Its guarantees require an approximately k-sparse signal with a small tail,
  and this regime is the opposite: a dense noise floor with a peak 1.19x above
  the median. Its bucketing window was tried here and makes things worse
  (worst case 0.19 against 0.57 without), because narrowing in lag means
  narrowing in frequency, which throws away band.
