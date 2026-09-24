# What is left, and what is closed

A catalogue of every improvement considered for the hierarchical filter, with
the evidence for each. The point of writing it down is that most of the
plausible-sounding ones are already dead, and the reasons are not obvious --
several were re-derived two or three times across sessions before being
measured.

Nothing here assumes the templates are chirps, are related to each other, or
come from any particular field. Approaches that require those assumptions are
listed in "Requires relaxing a constraint" and are not planned.

## Where the time actually goes

Per pair, TSC ticks, 37 templates, n=4096, band 1024:

| stage | threshold 5.0 | threshold 5.5 |
|---|---:|---:|
| even coarse pass | 2172 (75%) | 2105 (90%) |
| odd coarse pass | 541 (19%) | 186 (8%) |
| reconstruction | 165 (6%) | 25 (1%) |
| output fill | 24 (1%) | 23 (1%) |

Every pair pays the even pass. Nothing else is close. **Any plan that does not
touch the even pass is worth at most 25%, and at the higher threshold at most
10%.**

## The one number that kills most ideas

The true coarse maximum has a coefficient of variation of 0.103, so the coarse threshold
sits only **1.19x above the median**. A pre-filter rejects a pair only when
`stat/worst_case_recovery < margin`, so the rejection fraction depends on one
property of the statistic -- its worst-case recovery -- and the curve has a
cliff:

| worst-case recovery | rejects at the 5% margin |
|---:|---:|
| 0.70 | 1.2% |
| 0.85 | 53.3% |
| 0.95 | 88.2% |

**A statistic must clear ~0.85 worst-case recovery to be worth anything at
all.** Everything that decimates lags, narrows the band, or bounds by energy
lands between 0.16 and 0.67. This single fact is why the list of closed
avenues below is so long.

## Live

### 1. A minimax interpolation kernel for the bracket

The bracket is now on and winning, and its ceiling is the whole odd pass: 19%
of the cost at threshold 5.0, 8% at 5.5. What limits it is the worst-case
accuracy of the interpolated statistic, which sets the sound reject bound
`ilo <= min(S/true)/graw`.

That accuracy **saturates with tap count** -- 0.8384 at 9 taps, 0.8855 at 13,
0.8931 at 17, and 0.8931 again at 21. Two lengths giving the identical worst
case says the limit is the design criterion, not the length: the taps come from
a weighted least-squares fit, which minimises mean-squared error and does
nothing about the tail. A minimax (Chebyshev) design optimises exactly the
quantity the bound depends on.

If it moved `min(S/true)` from 0.893 to 0.95, `ilo` could rise from 0.912 to
0.978, and the measured `ilo` sweep says that roughly halves the odd pass again.
Worth up to ~10% overall. This is the best-posed live item on the page.

### 2. Key the tables on the decimation ratio, not on n and band separately

The tables cover `n=4096` and nothing else, so four of the five transform
lengths the benchmark exercises get no answer at all. Measuring every length
outright is the brute-force fix and it is what is running; the interesting
question is whether most of that grid is redundant.

The hypothesis: given the reference's own `f(m)` and `B_eff(m)` at the band --
which the tables already key on, and which absorb the spectral difference
between lengths -- dismissal depends on the DECIMATION RATIO `R = n/m` rather
than on `n` and `m` separately. The coarse pass folds R bins into one and
searches a lag grid R times coarser, and R is what sets how much the
correlation peak is smeared; n on its own mostly sets the lag count, which
bears on the noise maximum rather than on whether the signal's own peak clears
the threshold.

There is already evidence that R is the axis that bites. Forcing bands at
snr 5.0 lost 34 triggers at band 1024 (R=4) against 8 at band 512 (R=8), which
is not how a merely-strict threshold behaves -- it is the deterministic `g` and
`graw` running optimistic at small R.

If it holds, a row measured at `n=4096, m=1024` speaks for `n=16384, m=4096`,
and the table collapses from one grid per length to one grid in R. That is the
difference between retuning for a new transform length and not having to.

This is testable against the sweep now running without any new measurement:
it covers five lengths with overlapping ratios, so the same R appears at
several n. If dismissal at fixed (R, f, B_eff) agrees across n, the axis is
real; if it does not, the tables stay per-length and this item closes.

### 3. Measure cost on a BANK, not on one template

The cost half of the tuning is measured with `ntemplates=1` and the time then
divided by `nt` as though a batch had been filtered. It measures the unbatched
regime and labels it batched. Real callers run a bank -- 37 templates in
`pycbc_inspiral_fir` -- where the coarse pass amortises across templates and
the interpolation tap count scales differently.

That is the largest known error in selection, and it is bias rather than
noise. Regenerating the table with eight independent noise realisations a
cell, which takes the ratio CV from 3.3% to under 1% at n=4096, made selection
WORSE, not better:

    point          in use   better-sampled
    4096 @ 6.0      100%         91%
    8192 @ 5.0      100%         86%
    16384 @ 6.0      95%         92%

The feature grids are identical and the cost ordering is identical. What
changed is the gap -- 3.5% against 6.1% between 512/2/8 and 512/2/4 at n=4096
snr 6.0 -- where measurement says 512/2/4 is 10.6% FASTER. Both tables have
the sign wrong; the better one is wrong by more, so the 5% tie-break that was
rescuing it no longer fires. Sampling converged onto a biased value.

The tap axis is where it shows, which is what a one-template harness would
predict: with a single template there is nothing for the coarse pass to
amortise against, so K=4's advantage over K=8 never appears.

What it needs: build the cost plans with a realistic bank, re-measure, and
re-score with `tools/score_selection.py`. If the bias goes, `_COST_TIE` in
`choose_config` should be deleted rather than retuned -- it exists only to
mask this.

### 4. Choose the batch tiling, instead of streaming the whole bank

**What exists.** The hierarchical `run_series` groups data blocks internally:
`dgroup = 8`, measured rather than assumed, and the table that settled it is
in `src/hmf.c` -- 8 is best or within a percent at 37, 74, 128, 256 and 418
templates. It is capped by a 4 MB staging bound at long `n` and overridable
with `MF_DGROUP`. The caller never sees it, which is the point.

**What does not exist.** Nothing tiles the TEMPLATE axis. For each group of
data blocks the whole bank streams past, so a bank that does not fit in cache
is re-read once per group. `run(templates=(t0, nt))` lets a caller slice the
bank by hand, but the library makes no decision about it, and the flat
`MatchedFilter` makes none at all -- it uses whatever `(ndata, ntemplates)` it
was given.

**Why a tile should win.** D x T is a symmetric product, and the operand
traffic is not symmetric with the shape. A `d x t` tile reads `d + t` operands
to produce `d * t` products: a 16x1 tile reads 17 operands for 16 products,
while 4x4 reads 8 for the same 16. Squarer tiles move half the memory per
product, and once the working set stops fitting in L2 that is the term that
decides. This is the ordinary blocking argument from dense linear algebra and
there is no reason it should not apply here.

**Why it is not done.** The measurement to justify a specific tiling has not
been made cleanly. `measure_cost` already takes `nt` and `nd`, and the cost
table's schema has room for them, but `pairs_target` holds TOTAL PAIRS fixed:
a 1x1 shape then runs 200 tiny calls against 5 large ones at 64x64, so most of
what separates them is per-call overhead rather than throughput. A docstring
here claimed "up to 1.94x" on the strength of that harness and the number
reached the benchmark page before anyone asked where it came from. It has been
removed rather than defended.

**What it needs.** Hold work per call fixed rather than pairs; sweep `(nd, nt)`
on a log grid at several `n` and bank sizes; check whether the shape factor is
separable from the configuration, because if it is, it is one extra column
rather than a cross product with every existing axis. Then the same
refuse-or-measure rule the band and margin already follow can pick the tiling,
and the caller can go on handing over everything it has.

### 5. Template support pruning -- small here, real for the flat filter

Measured on the captures: templates are **exactly zero in 2047 of 4096 bins**.
The product is therefore zero above n/2, and half the full filter's product
work multiplies zeros. Two consequences:

- The product halves: 24576 -> 12288 flops per full-filter pair.
- The inverse transform of a half-supported spectrum is two transforms of n/2
  (`y[2j]` and `y[2j+1]` from `P` and `P` modulated), costing `5n(log n - 1)`
  against `5n log n` -- 8.3% at n=4096.

Together ~12% of the full filter. That is 12% of the reconstruction path, which
is 6% of the hierarchical cost, so **0.7% here** -- but 12% for anyone using
`MatchedFilter` directly, and it would make the flat baseline honest.

Detect the support at ingest (measure it, do not assume it); a filter that is
dense gets the current path.

### 6. Output protocol

`fill` writes zeroed peak records for the 98.5% of pairs that report nothing.
Returning fired peaks plus a count instead would remove it. Worth 1%, and it
changes the API.

## Done

### A GPU backend, in the same wheel

`device="gpu"` runs the full API -- index and complex value, per bin, with a
window and an arbitrary binsize -- on any Vulkan device, and is covered by
the same tests as the CPU, parametrised over device.

**How it is built.** One Slang source, `src/gpu/tierb.slang`, specialised by
transform length and compiled to SPIR-V ahead of time by
`tools/build_spirv.py`. The blobs ship inside the wheel and are dispatched by
`_vkcompute.py`, a ctypes layer over the system Vulkan loader. Nothing at run
time imports a shader compiler and there is no second wheel to choose, which
was the constraint the design started from.

**What it cost to get right.** The transform leaves its output in mixed-radix
digit-reversed order, because the four-step skips its final transposes. A
peak *magnitude* is order-independent, so nothing needed to know this until
the kernel had to report an index and place samples into bins -- and getting
it wrong would have been silent. It was established by dumping every register
against a float64 reference at all five lengths and fitting; see
`tools/gpu_output_order.py`.

**Still open.** Transform lengths above 16384 need more than one workgroup
and are not implemented. `run()` allocates and frees its device buffers per
call, so the measured end-to-end time is well above the kernel time; buffer
reuse is the obvious next step, and the CPU path already does it. Per-device
cost tables do not exist, so the hierarchical mode's selection still prices
everything with CPU numbers.

### Choosing the band and the coarse threshold from the reference, jointly

This was the largest live item on the page and it is now shipped. Kept here in
summary because the argument is still the reason the design looks as it does.

**The problem it solved.** Band selection was `hmf_choose(n, snr, fd, ...)`, a
nearest-neighbour lookup over hardcoded design points that never saw the signal
power, while the coarse threshold *was* power-aware. Half the decision used the reference
and half ignored it, and the two cannot be separated: band 1024 alone at margin
1.00 misses 31/842, so the table picked 2048 and bought the accuracy back with
bandwidth. Narrow the band without fixing the coarse threshold and triggers are lost; fix
the coarse threshold without narrowing the band and the saving is left on the table.

**What shipped.** Two measured tables, `accuracy.txt` and `cost.txt`, shipped
as package data and read at `set_reference` time. They are split because they
are different kinds of fact: dismissal is a property of the algorithm, cost is
a property of the machine, and a user retuning for their own CPU must be able
to replace one without touching the other. `choose_config` computes the
reference's in-band fraction and effective bandwidth at each candidate band,
keeps the configurations whose measured dismissal meets the budget, and takes
the cheapest. There is no compiled design table and no model: a fit that does
not promise the budget should not answer in the budget's name.

**Outside the tables it refuses.** That is the point of measuring rather than
modelling, and it is why `tools/hmf_tune.py` ships -- coverage is extended by
running it, not by extrapolating.

**Two faults found by measurement, both worth remembering.** The accuracy half
was built from a numpy re-derivation of the statistic rather than the real
filter, and reported FD = 0.0 for a configuration that triggers 60% of the
time; the tuner now drives the actual code path, so a code change invalidates
the table rather than silently disagreeing with it. The cost half built a
separate synthetic reference per cell, so band 512 and band 1024 were timed on
different signals -- not a noisy comparison but not a comparison at all -- and
it ranked the slowest of four admissible options first. Cost is now measured by
holding one reference fixed and timing every configuration against a pivot in
the same loop, and stored as a ratio, so machine, clock state and contention
cancel.

**What is left here.** Coverage, and resolution. Most admitted cells read 0.0
dismissal, which is the trials floor rather than a demonstration of safety, and
`U=2` is the only oversampling measured -- so oversampling is not really a
selected setting yet.

## The coarse pass, examined directly

It is 75-90% of the cost, so it gets its own section. Everything below was
measured with the baseline and the variant rebuilt and run **interleaved** in
the same session -- this machine's baseline drifts ~9% between mornings, and
two conclusions on this page had to be withdrawn after being drawn across that
gap.

### Nothing cheaper can precede it
The even-pass threshold sits at only **1.064x the median even maximum** (CV 0.091), which
is a steeper cliff than the final margin's 1.19x. A pre-filter placed before the
even pass rejects:

| worst-case recovery | 0.70 | 0.80 | 0.85 | 0.90 | 0.95 |
|---|---:|---:|---:|---:|---:|
| fraction rejected | 0.0% | 1.8% | 11.4% | 31.0% | 53.3% |

It needs **0.90 just to reject a third**. The best cheap statistic ever
measured here is 0.67. The coarse pass cannot be avoided for any useful
fraction of pairs.

### Folding instead of truncating -- exact, and worse
The coarse pass keeps the first m bins of the product. The decimation identity
says the stride-R correlation is *exactly* the m-point transform of the
**folded** product, `P_fold[k] = sum_r P[k+r*m]`, and that is confirmed to
float64 round-off (4.2e-16) where truncation's worst case against the same
target is 0.9092.

It still loses, because the two errors are coupled. Band-limiting discards
energy but **widens** the correlation peak, and that width is what makes the
coarse lag grid adequate. Folding returns the sharp full-band peak onto the
same grid, so scalloping gets worse. Against the true continuous peak:

| | median | p1 | **worst** |
|---|---:|---:|---:|
| truncate (current) | 0.9772 | 0.9192 | **0.9116** |
| fold (exact in frequency) | 0.9879 | 0.9034 | **0.8915** |

The margin is set by the worst case, so folding makes it worse. Truncation is not
a cost-saving approximation that happens to work -- it is load-bearing, and it
is why the band has a real optimum rather than being "as wide as affordable".

### Codelet radix
The 32-point element transform uses split-radix (`fftsr32`); radix [8,4]
(`fft32_84`) is also generated. Swapped and measured: 2300 against 2319 median
ticks. Split-radix stays.

### binmax is 10-11%, and three attempts to reduce it all failed
Ablating the magnitude, compare, select and mask-test out of the lag loop saves
**231-255 ticks a pair, 10-11% of the coarse pass** (interleaved, two rounds).
Splitting that further: ablating *only* the magnitude saves nothing -- the
`FMA+MUL` overlaps with the transform entirely. The cost is the compare and
mask-test, and it is plain op count, not a stall:

- **Branchless** (always select, no `V_MASK_ANY`): 2389 against 2366. No.
- **Compare against the fixed threshold** rather than the running maximum, to
  break the loop-carried dependency -- exact, since anything that can raise the
  maximum must already exceed the threshold: 0.987 / 1.012 interleaved. No.
- **Hoisting the window test** out of the loop by solving for the interior run
  of lags: 0.987 / 0.977 / 0.940. Worse -- the second loop body costs more in
  code size and scheduling than the hoisted test saves.

The loop is already at its tuned shape. What has *not* been tried is a
**grouped reduction**: compute `m2` for four vectors, `V_MAX` them together and
do one compare and one mask-test instead of four of each, with a rare fixup to
identify which vector won. That trades 3 compares and 3 mask-tests for 3 maxes
per group of four -- about 37% of the compare cost, so ~3% of the total. It is
the only untried idea for this loop, and at 3% it sits close to this machine's
±1% measurement noise, so it needs interleaved A/B over several rounds to
settle.

## Closed, with evidence

### Parallelism
**Ruled out by the contract** on the CPU, not by measurement. Single-threaded
is the design there; callers run one process per core. The GPU backend is a
separate answer to the same question rather than an exception to this: it is
still one call from one thread, and the parallelism is inside the device.

### Non-power-of-two transform sizes
**Closed twice over.**

*Block size.* Cost per useful output sample is `n log n / (n - ntaps + 1)`:
14.10 at 2048, **13.48 at 4096**, 13.76 at 8192, 14.40 at 16384. 4096 is the
optimum and the curve is flat around it, so an intermediate size gains nothing
even before the mixed-radix penalty.

*Band.* The zero-loss cost against band is 20.97 ms at 512, 13.18 at 1024,
15.92 at 2048. A parabola through those has its minimum at band **1209**, worth
12.88 ms -- a **2.3% ceiling**, which is less than radix-3/5 codelets cost
relative to radix-2/4/8. Also checked that band 2048 does not tolerate a higher
margin to compensate: at margin 1.06 it misses 638/842.

### Finer oversampling (U=4)
**Closed.** U improves only the lag-grid scalloping loss, and that factor is
already accurate. Measured recovery of the U-fold grid against the continuous
maximum on 624 real pairs: U=1 worst 0.7908, U=2 **0.8963**, U=4 0.9820, U=8
0.9958, tracking the `sinc(1/2U)` bound. U=4 would move a factor from 0.90 to
0.98 -- but the factor that actually binds the coarse threshold is `g`, which is 0.88-0.91
and is about band-limiting, not scalloping. The kernel hard-limits U to {1,2};
U=1 misses 244/842, so the odd pass is not optional.

### A more conservative even-pass threshold
**Closed.** Sweeping `even_margin` *downward* -- 0.92, 0.88, 0.84, 0.80 -- the
miss count stays at exactly 31/842 while the cost rises 41% (10.12 to 14.26
ms/segment). **None of the misses come from the even-pass threshold.** All of them come
from the main margin, i.e. from `g`. Upward it breaks immediately (0.96 costs 3),
so 0.92 is both correct and tight.


### Narrow types (int16, int8)
**Closed.** int16's entire value is doubling the lanes, and the even pass is
already width-insensitive: within one ISA, `AP_W=8` gives 2032/2055/2044 ticks
and `AP_W=16` gives 2020/2026/2151. Across ISAs the saturation is visible --
4 lanes 4677, 8 lanes 2274, 16 lanes 2017, so 2.06x for the first doubling and
1.13x for the second. 32 int16 lanes buy nothing and make the corner turn worse
(32x32 transpose instead of 16x16). int8 is separately measured *slower* than
int16 on the arithmetic itself (0.54x).

Precision was never the obstacle: a full Q15 pipeline modelled on 456 real
pairs -- exact int32 product, one renormalising shift, unconditional `>>1` per
stage, no block-floating-point reduction -- gives a **1.0125x** error band
against a 1.19x margin, with zero saturation. See `tools/coarse_fixed.py`
and `docs/coarse-narrow.md`.

### Stage-A Parseval bound
**Closed.** After stage A the energy of each residue class of lags is free, and
the class maximum is bounded by its square root. Measured on real pairs, the
bound is 2.5-4.9x the true maximum, i.e. worst-case recovery **0.16 to 0.39** --
far under the 0.85 cliff, so it rejects essentially nothing at our margin.
Tested at 32, 64 and 128 classes, both as consecutive blocks and as residues.

### Any cheaper pre-filter
**Closed** by the recovery cliff. Measured: Parseval/L1/cheap features ~0.1;
lag decimation F=8 0.39, F=2 0.67; multi-offset F=4x2 0.65; semi-coherent
stacking reaches 0.97 but costs 0.94 of the full pass. The only statistic that
clears 0.85 is interpolation from an already-computed transform, which is the
bracket.

### Sparse FFT
**Closed.** Wrong regime. Its guarantees need an approximately k-sparse signal
with a small tail; this is a dense noise floor with a peak 1.19x above the
median. Its bucketing window was tried and makes things worse (0.19 against
0.57), because narrowing in lag means narrowing in frequency.

### FFT output pruning
**Closed by arithmetic.** We need the first m of n bins with m = n/4. Output
pruning decomposes into 4 transforms of length m plus 4 mult-adds per bin:
237568 flops against 245760 for the full transform -- a 3% saving. Pruning pays
when a *few* outputs are wanted, not a quarter of them.

### Band width
**Closed.** Swept over all twelve captures. Band 1024 is optimal at *both*
operating points: at zero loss, band 1024 at margin 0.94 costs 14.77 ms against
band 512 at margin 0.90 needing 20.97 ms. Band 512 wins only in the 3-6 missed
regime, which is not an operating point anyone wants.

### Four-step factorisation and blocking
**Closed.** m=1024 at 32x32 gives 2013-2048 ticks against 2260 at 16 and 2301
at 64. `MF_GBLK` and `MF_BBLK` move it by nothing (2210-2285 across all
settings).

### Coarse threshold margins
**Closed.** `even_margin` 0.92 is optimal: 0.96 costs 3 triggers of 842 and
1.00 costs 16. The scalloping bound alone is not sufficient; the extra factor
is doing real work.

### Overlap-save block size
**Closed by arithmetic.** Cost per useful output sample is
`n log n / (n - ntaps + 1)`: 14.10 at n=2048, **13.48 at 4096**, 13.76 at 8192.
Already at the optimum, and the coarse pass scales the same way since the band
must grow with n to cover the same frequency range.

### Sharing work between the even and odd passes
**Closed by algebra.** The odd series is `IFFT(P * phi)` with
`phi[k] = e^{i*pi*k/m}`. In the four-step index map phi separates into a
per-group phase and a within-group phase, but the within-group part is a
half-bin frequency shift, which is not a permutation -- recovering it from the
even transform is a dense Dirichlet convolution, O(N2^2). One 2m-point
transform instead of even+odd costs `2m log 2m` against
`m log m * (1 + 0.24)`, so the current two-transform scheme is cheaper
precisely because the odd one is usually skipped.

### Early exit inside stage B
**Closed.** A pair could stop as soon as a partial maximum clears the coarse threshold --
but that only helps pairs that fire, which are 1.5%. The 98.5% that do not fire
must finish regardless.

### Batching the reconstruction
**Closed.** Fires are a sparse scatter over the D x T rectangle: at 1.5% and 37
templates the smallest covering rectangle over a group of 8 segments runs ~32
pair-transforms for ~4 real ones. A single 1x1 reconstruction costs 15340 ticks
against 9805 for a batched pair, but the 8x waste dominates. Its overhead is
also not call overhead, it is streaming two 32 KiB spectra for one pair, which
batching a sparse set cannot avoid.

### Searching for an instruction sequence to replace the coarse stage
**Closed.** A streaming register-machine search over three-address programs
with bit-level ops reached a bracket width of 1.62 against the ~1.2 needed to
settle anything. The space reachable by single-instruction mutation does not
contain a phasor, so it cannot find anything Fourier-like; a fair attempt needs
batched fitness evaluation and seeding from known primitives. Published
superoptimisers (AlphaDev, STOKE) rely on exact-semantics equivalence checking,
which an approximate surrogate does not admit.

## Requires relaxing a constraint

Listed for completeness. All are ruled out by the library's contract, not by
measurement.

- **Cross-template structure** (SVD or conic compression of the bank,
  interpolating the statistic across neighbouring templates). This is where the
  large published gains in bank-based searches live, and it is explicitly out:
  "do not compare between templates".
- **Assuming the template's time-frequency structure** (multi-rate filtering:
  split the filter into time slices and downsample the early, low-bandwidth
  ones). Requires knowing the filter is a chirp. Ruled out by "you can't assume
  the form of the template in the code itself". A measured variant -- detect
  each filter's time-frequency support at ingest -- is not obviously cheap
  enough to pay, because the support measurement is per template and the gain
  is per pair.
- **Approximate output.** The guarantee is that every reported peak is
  bit-identical to the flat filter's. Reconstruction cannot be approximated.

## Summary

The even coarse pass is 75-90% of the cost, runs at ~60% of a realistic FFT
ceiling, is 3.4x faster than pocketfft while doing more work, and is immune to
element width, blocking, factorisation, band choice and transform size. Every
cheaper statistic that could avoid it fails the 0.85 recovery cliff. **It is
the floor of this algorithm**, and any plan that does not touch it is capped at
25% -- 10% at the higher threshold.

Of what remains, one item is well posed: the bracket's reject bound is limited
by a least-squares tap design whose worst-case accuracy saturates at 17 taps,
and a minimax design optimises exactly the quantity the bound depends on. That
is worth up to ~10%.

Band and margin selection is done: it is driven by two measured tables read from
the caller's reference, and on the captures it moves the pick from the slowest
admissible configuration to the fastest, 21% at unchanged accuracy. What is
left there is coverage and resolution, not method. Everything else on this page
is closed.
