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

### 1. Calibration -- the only large one left

The recovery factors `g`, `graw`, `graw1` are derived from the reference's
*mean* frequency series. A mean is not a bound on an individual realisation, so
the gate is set optimistically and the filter misses 31/842 triggers at the
default gate against a stated budget of 1e-3. Buying those back costs a 6% gate
cut and 24% of the speed: 3.60x becomes 2.74x.

The diagnostic states the gap directly: `g` measured from realisations is
**0.7022** where the code uses the noiseless **0.9995**.

Closing it is worth **1.31x at the zero-loss operating point** -- more than
every other live item combined. It is not a tuning exercise; it means replacing
a global constant with a per-pair quantity. The obvious candidate is a bound
derived from the out-of-band energy of the actual product, which is computable
(`sum |D_k|^2 |H_k|^2` outside the band) but costs ~20% of the even pass to
evaluate, so the work is in finding a cheaper sufficient statistic or in
computing it once per block rather than per pair.

Deliberately parked by the user until the hierarchy itself is exhausted. It now
effectively is.

### 2. Parallelism -- structurally the largest, currently out of scope

The library is single-threaded by design. The D x T pair loop is embarrassingly
parallel with no shared mutable state except the output array, which is already
indexed per pair. On a 16-core machine this is a ~10-14x wall-clock win, an
order of magnitude more than anything else on this page.

Not planned because single-threaded is the current contract (callers run one
process per core). Worth revisiting only if that contract changes.

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

### 4. Odd pass, via a better interpolation kernel

The bracket settles pairs without the second coarse transform and is currently
break-even when its reject bound is set soundly. Its quality is set by the
interpolation kernel: going from 9 to 13 taps moved the measured worst-case
`min(S/true)` from 0.8384 to 0.8855, which moves the sound `ilo` from 0.8635 to
0.9120. A kernel designed to maximise the *worst case* rather than the
least-squares fit might move it far enough to make the bracket pay. Ceiling is
the whole odd pass: 19% at threshold 5.0, 8% at 5.5.

### 5. Output protocol

`fill` writes zeroed peak records for the 98.5% of pairs that report nothing.
Returning fired peaks plus a count instead would remove it. Worth 1%, and it
changes the API.

## Closed, with evidence

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
element width, blocking, factorisation and band choice. Every cheaper statistic
that could avoid it fails the 0.85 recovery cliff. **It is the floor of this
algorithm.**

The remaining headroom is not in the hierarchy at all. It is in the gate
calibration, which is worth 1.31x at the operating point that matters, and in
parallelism, which is worth an order of magnitude and is a contract decision
rather than an engineering one.
