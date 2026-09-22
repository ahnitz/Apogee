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

The true coarse maximum has a coefficient of variation of 0.103, so the gate
sits only **1.19x above the median**. A pre-filter rejects a pair only when
`stat/worst_case_recovery < gate`, so the rejection fraction depends on one
property of the statistic -- its worst-case recovery -- and the curve has a
cliff:

| worst-case recovery | rejects at the 5% gate |
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

### 2. Calibration -- worth correctness, not speed

The recovery factor `g` is derived from a noiseless autocorrelation and is
0.9995, where the honest quantity is the ratio of the coarse statistic to the
**full filter's** statistic on the same realisation. Measured on 4440 real
pairs: median 0.9761, p1 0.9125, p0.1 0.8837, min 0.8660.

So a principled `g` lands near 0.88-0.91. Applied through
`hmf_threshold(fpow*g^2, ...)` that is a ~9% cut in the gate, against the 6%
that `gate_margin=0.94` already applies by hand. **It would reproduce the
existing zero-loss operating point, not beat it.** The value is that the point
becomes automatic instead of user-tuned, and that the fitted `gscale=1.40`
disappears.

A *per-template* `g` looked like the speed win -- per-template worst cases
spread 0.866 to 0.928 -- but that spread is sampling noise: splitting each
template's samples in half and correlating the two halves' p10 gives
**r = 0.218**. The templates genuinely have the same recovery. A global
constant is the right model.

### 3. Template support pruning -- small here, real for the flat filter

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

### 4. Output protocol

`fill` writes zeroed peak records for the 98.5% of pairs that report nothing.
Returning fired peaks plus a count instead would remove it. Worth 1%, and it
changes the API.

## The coarse pass, examined directly

It is 75-90% of the cost, so it gets its own section. Everything below was
measured with the baseline and the variant rebuilt and run **interleaved** in
the same session -- this machine's baseline drifts ~9% between mornings, and
two conclusions on this page had to be withdrawn after being drawn across that
gap.

### Nothing cheaper can precede it
The even gate sits at only **1.064x the median even maximum** (CV 0.091), which
is a steeper cliff than the final gate's 1.19x. A pre-filter placed before the
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

The gate is set by the worst case, so folding makes it worse. Truncation is not
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
**Ruled out by the contract**, not by measurement. Single-threaded is the
design; callers run one process per core.

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
gate to compensate: at gate 1.06 it misses 638/842.

### Finer oversampling (U=4)
**Closed.** U improves only the lag-grid scalloping loss, and that factor is
already accurate. Measured recovery of the U-fold grid against the continuous
maximum on 624 real pairs: U=1 worst 0.7908, U=2 **0.8963**, U=4 0.9820, U=8
0.9958, tracking the `sinc(1/2U)` bound. U=4 would move a factor from 0.90 to
0.98 -- but the factor that actually binds the gate is `g`, which is 0.88-0.91
and is about band-limiting, not scalloping. The kernel hard-limits U to {1,2};
U=1 misses 244/842, so the odd pass is not optional.

### A more conservative even gate
**Closed.** Sweeping `even_margin` *downward* -- 0.92, 0.88, 0.84, 0.80 -- the
miss count stays at exactly 31/842 while the cost rises 41% (10.12 to 14.26
ms/segment). **None of the misses come from the even gate.** All of them come
from the main gate, i.e. from `g`. Upward it breaks immediately (0.96 costs 3),
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
against a 1.19x gate margin, with zero saturation. See `tools/coarse_fixed.py`
and `docs/coarse-narrow.md`.

### Stage-A Parseval bound
**Closed.** After stage A the energy of each residue class of lags is free, and
the class maximum is bounded by its square root. Measured on real pairs, the
bound is 2.5-4.9x the true maximum, i.e. worst-case recovery **0.16 to 0.39** --
far under the 0.85 cliff, so it rejects essentially nothing at our gate.
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
operating points: at zero loss, band 1024 at gate 0.94 costs 14.77 ms against
band 512 at gate 0.90 needing 20.97 ms. Band 512 wins only in the 3-6 missed
regime, which is not an operating point anyone wants.

### Four-step factorisation and blocking
**Closed.** m=1024 at 32x32 gives 2013-2048 ticks against 2260 at 16 and 2301
at 64. `MF_GBLK` and `MF_BBLK` move it by nothing (2210-2285 across all
settings).

### Gate margins
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
**Closed.** A pair could stop as soon as a partial maximum clears the gate --
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

Calibration is a correctness item, not a speed one -- the honest `g` reproduces
the hand-tuned `gate_margin=0.94` rather than beating it, and the per-template
version is sampling noise. Everything else on this page is closed.
