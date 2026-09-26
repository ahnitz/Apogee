# The hierarchical matched filter

The hierarchical filter assumes that enough of a template's signal-to-noise
sits in the low part of its band for a narrow slice to bound the full result.
Where that holds, it correlates only that slice, on a coarse lag grid, and pays
for the full correlation only where the coarse result could still become a
detection.  Where it does not hold -- power spread flat across the band, or
concentrated high -- the slice bounds nothing useful and the pre-pass is added
cost with no saving.

The guarantee is deliberately one-sided.  Every peak it reports is
**bit-identical** to `ap_mf_run`'s, because when the coarse pass escalates it *is*
`ap_mf_run`.  It never invents a peak and never shifts one.  What it can do is
miss one, with probability at most `fd` for a signal of strength `snr`.

## Where the speedup comes from

    cost  =  coarse transform  +  threshold scan  +  refine rate x full correlation

The trigger rate is the whole game.  It falls off as `exp(-t_c^2/2)` per coarse
sample, so a coarse threshold a few tenths higher is worth more than any amount of
micro-optimisation in the coarse pass.  Everything below is in service of
raising `t_c` without breaking the false-dismissal bound.

## Why the coarse grid is oversampled

Keeping the lowest `m` bins and transforming `m` points samples the coarse
series at exactly its Nyquist rate.  The correlation peak is then up to 18% low
between samples ("scalloping"), and that loss comes straight off `t_c`.

At equal transform cost, **zero-padding a narrow band beats filling a wide one**:

      G  band  U      f    raw   interp   sqrt(f) x recovery
    512   512  1  0.850  82.1%   82.1%          0.757
    512   256  2  0.772  94.0%  100.0%          0.879

Dropping `f` from 0.850 to 0.772 buys back more in scalloping than it costs in
band.  So the coarse stage takes a narrower band and oversamples it.

## Why that is not a zero-padded transform

Output parity splits it exactly:

    even k:  m-point transform of Q
    odd  k:  m-point transform of Q[f] * exp(i pi f/m)

The odd twiddle is a half-sample shift, so it folds into a second stored
template at ingest - preprocessing is free here - and costs nothing at run time.
U=2 is therefore **two m-point transforms**, not one 2m-point transform: 11%
cheaper at m=512, with no new transform size and the same fused-product path.

## The interpolator

The coarse series is **analytic** - its spectrum is on [0,1), not [-1/2,1/2) -
so a plain sinc is the wrong kernel: it relabels every bin above m/2 as a
negative frequency.  It agrees *exactly* at the integer samples, which is why
that error hides from spot checks; it is wrong only between them.  The correct
kernel is the periodic Dirichlet one,

    D(x) = e^{i pi x (m-1)/m} sin(pi x) / (m sin(pi x/m))  ~  e^{i pi x} sinc(x)

a modulated sinc.  Two consequences worth stating plainly:

- **Eight taps are enough, and windowing hurts at U=1.**  At U=2, 8 taps recover
  100.0% and 12 or 16 add nothing.  At U=1 no tap count helps much, and every
  window makes it worse, monotonically - a window's transition band needs empty
  spectrum to sit in, and critical sampling has none.
- **The coarse pass only needs `|v|`**, and the re-modulation phase has unit magnitude,
  so it cancels.  demodulate -> interpolate -> re-modulate collapses into one
  complex tap `w_k * exp(i pi (d-k)/U)` applied to the raw series.

Because the fine grid is an exact integer subdivision of the coarse one, the tap
bank needs `HMF_NSUB` rows rather than the ~1024 a general resampler would: a few
hundred bytes, L1-resident, effectively a polyphase bank.

## Calibrating the coarse threshold

With the band split, `rho_c = sqrt(f) rho_full + sqrt(1-f) xi` with `xi`
independent.  Conditional on the full-filter value, the coarse value is Gaussian
about `sqrt(f) rho_full`, so the false-dismissal probability is a Rice CDF,
marginalised over the detected population.  That is analytic, which matters: at
`fd = 1e-4` a Monte Carlo quantile has a handful of events in its tail and is far
too noisy to design against.

Two conditioning mistakes, both of which were made and caught here:

- Not conditioning on detection at all makes the estimate ~10x **optimistic** -
  it counts events the full filter never reported.
- Pinning `rho_full` to the threshold instead of integrating over it makes it
  ~10x **conservative**, which is safe but sets `t_c` too low and inflates the
  trigger rate.

Done correctly the model agrees with Monte Carlo within ~25% and is conservative
at every point tested.  The residual margin is because the recovery factor is
worst-case over sub-grid offsets while the simulation averages over them - the
right direction for a guarantee.

`tools/hmf_design.py` does all of this offline and emits `src/hmf_table.h`.
Nothing is searched at run time.

## Two factors, not one

The table stores **two** recovery figures and they are not interchangeable:

- `g` - what the interpolator recovers.  Calibrates `t_c`.
- `graw` - what a raw sample recovers.  Bounds the cheap pre-scan that decides
  which samples are worth interpolating.

They differ by ~6% at U=2 and ~18% at U=1.  Using `g` for the pre-scan discards
exactly the samples interpolation exists to rescue, and adds false dismissals on
top of the calibrated rate without any test noticing unless it counts omissions.

## What `fd` promises, and what it does not

`fd` is a budget on dismissed **signals**.  It is NOT a promise that the
hierarchical filter reproduces the flat filter's trigger list, and on
marginal noise the two differ by a great deal.  Measured at threshold 5.0,
with the same plan meeting its budget on the same data:

    band   flat NOISE triggers dismissed    injections at snr 5.2 dismissed
           captured    synthetic            captured (of 2400)
     256    5.7e-2      3.8e-1               0     (< 4.2e-4)
     512    2.4e-2      3.7e-1               0
    1024    3.6e-3      2.7e-1               0
    2048    0           0                    --    (f = 1.0000)

Selection picks band 512 for that reference, so the shipped default loses a
few percent of captured marginal noise triggers and a third of synthetic
ones, while losing no signals at all.

**This is the mechanism working, not a calibration defect.**  A coherent
signal deposits power across frequency exactly as the template does, so the
in-band fraction `f` applies and the coarse statistic is about `sqrt(f)`
times the full one, every time.  A noise fluctuation that reaches the
threshold got there by a draw, and its in-band part is an INDEPENDENT draw
with the same mean and a large variance -- so a good share of marginal
noise triggers land under the gate while signals at the same `|z|` do not.
Where `f` is 1.0 the coarse statistic IS the full one and nothing can be
dismissed; band 2048 measures exactly that, on both data sets.

It matters anyway, for two reasons.  A pipeline that estimates its
background from the trigger distribution is not filtering signals, and this
changes that distribution.  And a user comparing the two filters will see
this first, read it as a bug, and the obvious repair -- lower the gate --
throws the speedup away for nothing.  A caller who needs the flat filter's
trigger list exactly should use the flat filter, or a band where `f` is
1.0, which is not a hierarchical filter in any useful sense.

`tests/test_gate_population.py` asserts both halves so neither can be read
without the other.

### A bank that does not match its reference spends threshold headroom

The reference states how SNR accumulates for the bank being filtered, and a
bank matching it meets the budget.  A synthetic bank spanning exponents
-7/3 to -4/3 against a reference at -7/3 omits 66 of 508 injections at band
512 -- 130x the budget.

The mechanism is one line, `refresh_template()` in src/hmf.c:

    double f = p->ref_on ? p->ref_f : p->fpow[t];

The per-template in-band fraction `fpow[t]` is computed and then used only
when no reference is set.  With a reference -- the normal path, since
selection needs one -- every coarse template is scaled by `1/sqrt(f_ref)`,
so a template keeping less of its power in the band produces a coarse
statistic smaller by `sqrt(f_t / f_ref)` and is gated on a threshold
calibrated for `f_ref`.  Measured, the loss is monotone in the template's
own f: zero above f=0.936, 18.5% at 0.827, 48.3% at 0.739.

The captured PyCBC bank does not show it, and that looked like a
contradiction: 37 templates at f 0.636 to 0.786 against a reference at
0.9875 -- a predicted shortfall WORSE than the synthetic case -- dismissing
0 of 160.  The difference is headroom.  That capture runs at band 1024,
ratio 5.33, where the shipped threshold audits 2.5% BELOW the safe value;
the synthetic case runs at band 512, ratio 2.83, where it audits 4.1%
ABOVE.  Grid loss compounds it, since ratio 2.83 samples the correlation
peak half as finely.

So a heterogeneous bank is not safe or unsafe in itself.  It spends
threshold headroom that nothing accounts for, and whether that is
survivable depends on the band.  Using `fpow[t]` would normalise each
template by its own fraction and remove the dependence -- it is not done
here, because the threshold tables are calibrated against the reference and
changing the normalisation without re-calibrating them would trade a known
failure for an unmeasured one.  tests/test_heterogeneous_bank.py pins the
loss AND its shape, since a flat loss would be a threshold that is merely
too high and only an f-ordered one identifies this mechanism.

## Known limits

- **The decision is per pair, not per bin.**  The transform is global, so a partial
  one would not help; but it means a single loud bin drags the whole pair
  through the full correlation.
- **Bands 64 and 128 are supported but never selected.**  The transform
  handles them (the pair-batched path) and they are tested, but no cost rows
  are installed.  The blocker is not cost: at the reference it would be
  picked for, band 128 sits at ratio 1.24 and dismisses 2.9e-2 of injected
  signals against a 1e-3 budget, because the threshold table's low-ratio
  corner is optimistic by about 11%.  Band 128 is sound at ratio 2.68 and
  above, and band 256 is sound at 1.66, so this is the corner and not the
  band.  Enabling them needs measured threshold rows below ratio 1.5.  See
  docs/tooling-cleanup.md and tests/test_low_ratio_corner.py.  Explicit
  `band=128` works away from that corner; explicit `band=64` is refused at
  n=4096 for want of a calibrated threshold.
- **The trigger rate depends on the data.**  On noisier data than the design
  assumed the coarse pass escalates more often, and at a high enough rate the coarse pass
  is pure overhead.  `ap_hmf_stats` reports it; that is the first number to look
  at when the filter is slower than expected.

## Measured

One core of a Zen 5, AVX-512, D=T=16, bin n/4, whole record searched.  Per pair,
against the ordinary filter on the same inputs.

    pure noise - the coarse threshold should stay shut
      2^11 snr5.5 fd1e-2   band=256   mf= 1.24us  hmf= 0.64us   1.95x  trig= 0.0%
      2^12 snr5.5 fd1e-2   band=256   mf= 2.25us  hmf= 0.65us   3.48x  trig= 0.0%
      2^12 snr5.0 fd1e-4   band=1024  mf= 2.27us  hmf= 2.70us   0.84x  trig= 0.4%
      2^13 snr6.0 fd1e-2   band=512   mf= 5.30us  hmf= 1.49us   3.57x  trig= 0.0%
      2^14 snr5.5 fd1e-2   band=2048  mf=10.95us  hmf= 6.19us   1.77x  trig= 0.0%

    every segment carries a signal matching every template - worst case
      2^11 snr5.5 fd1e-2              mf= 1.36us  hmf= 2.02us   0.67x  trig=89.5%
      2^12 snr5.5 fd1e-2              mf= 2.39us  hmf= 3.03us   0.79x  trig=91.8%
      2^12 snr5.0 fd1e-4              mf= 2.50us  hmf= 5.39us   0.46x  trig=95.7%
      2^13 snr6.0 fd1e-2              mf= 5.28us  hmf= 5.82us   0.91x  trig=77.7%
      2^14 snr5.5 fd1e-2              mf=11.44us  hmf=17.63us   0.65x  trig=100%

Read these together, not separately.  The second block is a deliberate worst
case - every data segment carries a signal and every template matches it - so
nearly every pair triggers and the coarse pass is pure overhead on top of the
full correlation.  0.5-0.9x is the correct floor for that, not a defect.  Real
searches have many templates and few signals, which is the first block.

The `fd=1e-4, snr=5.0` row is the weak corner and is below 1x even on noise:
that combination forces `t_c` low enough that the coarse pass escalates on noise alone.
`ap_hmf_stats` exists so this is visible rather than mysterious.

The measured speedups on noise (1.95-3.57x) sit below the design model's
prediction (~4.7x at 2^11).  The model costs the coarse pass in flops, and small
transforms do not hit their flop bound - this is the gap between 5*m*log2(m) and
what a 256-point transform actually costs.

## A scan that was conservative and still wrong

The first working version interpolated around every sample that passed the cheap
pre-screen.  That is *safe* - strictly more places checked than the calibration
assumes, so it can never lose a detection - and it measured **0.08x**, twelve
times slower than the plain filter it was meant to beat.

The cause is worth remembering because it is invisible in the design model.  The
benchmark template has f = 0.994: its power is so concentrated that the
correlation peak is *broad*.  A broad peak's shoulder sits between `graw*margin`
and `margin` for ~100 consecutive samples, and each one paid 14 interpolations -
1360 per pair where 14 suffice.

The fix is also what makes the code match its own calibration.  `recovery()`
measures the interpolated maximum **around the global argmax**, so the scan
should do exactly that: one running-maximum pass with no sqrt and no branches,
then interpolate only around the winner, and only when the raw maximum lands in
`[graw*margin, margin)`.  Interpolations per pair fell from 1360 to 2.1 and the
worst case from 0.08x to 0.79x.

The general lesson: a margin that is conservative in the *statistical* sense can
still be catastrophic in the *computational* sense, and the test suite will not
notice, because conservative the coarse pass produces correct answers.  Only the
benchmark catches it, and only on data whose peak shape differs from the design
template's.

## Open: the coarse threshold does not behave as modelled at large N

At 2^18 and 2^20 the measured trigger rate disagrees with the design model, and
the disagreement is in the unsafe direction.

      n      model                        measured
    2^18   t_c=4.93, trig 50.4%, 1.04x    trig 0.0%, 5.01x
    2^20   t_c=1.32, trig  100%, 1.00x    trig 0.0%, 2933x

The model is the one to believe here.  The coarse threshold sits below the detection
threshold by construction, and with ~10^6 lags the coarse maximum in pure noise
reaches about sqrt(2 ln G) ~ 3.7 -- far above a margin of ~1.5.  Essentially every
pair should trigger.  A measured 0% means the run-time margin is much higher than
the calibration intends, and **a margin that is too high dismisses real signals
silently**.  Reported peaks stay bit-identical either way, so the test suite
cannot see this; only the trigger rate can.

Traced so far: the template's band fraction at 2^20 really is f=0.427, which
after the f_eff clamp should give t_c ~ 1.55 and fire on almost every pair.  The
C path does not do that and the cause is not yet found.

Two things this also makes clear, independent of the bug:

- **A realistic threshold at large N is not 5.5.**  The full filter alone
  expects n*exp(-t^2/2) noise crossings per pair - about 0.3 at 2^20 and t=5.5 -
  so a real search would set the threshold from the trials factor.  The
  hierarchical filter's usefulness depends on the margin between that threshold
  and sqrt(2 ln G), which shrinks as N grows.
- **The decision is per pair, not per bin.**  The output is one peak per bin, but
  one loud bin drags the whole pair through the full correlation.  For a search
  that wants a trigger in every window this is the binding limitation, and the
  cost model does not currently account for it.

Until this is resolved, treat 2^10..2^16 as measured and 2^18..2^20 as unverified.

## Next: int16 for the coarse stage

The phase profile puts the even coarse transform at 71% of the time below ~5%
trigger, running at 18.3 flops/cycle -- 57% of the AVX2 FMA peak.  It is not
overhead-bound, so the only way through is less arithmetic, and the coarse stage
is the one place in matchedfilter that can afford it: refinement is a separate exact
transform, so a ~1e-3 relative error in the coarse values cannot change a
reported peak, only the coarse threshold decision.

The int16 codelets already exist and are tested (`ffti16_8/16/32/64`, with and
without shift, covered by tests/test_units).  Band 256 splits 16x16, so both
stages land on `ffti16_16`.  What is missing is the driver:

1. Quantise the coarse product to Q15 with per-block scaling, tracking headroom.
   The existing `_ns` (no-shift) variants exist precisely for the blocks where
   headroom is provably sufficient.
2. An int16 stage A / stage B driver in balanced.c, fused with the product
   loader as the float path is.
3. An int16 binned maximum, or dequantise the few candidate lanes only.
4. **Re-calibrate g, graw and graw1 with the int16 kernel in the loop.**  This
   is not optional.  Quantisation changes the distribution of the coarse
   statistic, so inheriting float-calibrated recovery factors would leave the
   false-dismissal bound approximately right instead of exactly right -- which
   defeats the point of having a lever on it.  tests/test_hmf's omission-rate
   check is what verifies this held.

Expected gain: the codelets measured 1.55-1.64x on arithmetic.  With the even
transform at 71% of the low-trigger cells, that is roughly 1.4x overall there,
and nothing in the high-trigger cells, where refinement dominates and only the
trigger rate matters.

This is a substantial change, not a microoptimisation: a new transform path plus
a re-calibration.  It should not be attempted in a context too small to finish
and re-validate it, because a half-finished margin that is slightly wrong looks
*faster*, and the correctness suite cannot see it.

## The first-stage threshold can be set directly

`(snr, fd)` select a configuration -- band, oversample, taps -- and a level for
the first stage, from the offline sweep in `tools/hmf_design.py`.  That level
is a suggestion.  `ap_hmf_set_first_stage` (Python: `set_first_stage`) replaces
it with an SNR the caller chooses, leaving the configuration alone.

The distinction matters because changing `snr` at construction is *not* a way
to move the threshold: it selects a different row of the table, so band and
taps move with it.  Measured on a pycbc ratio search at a 5.5 SNR threshold,
constructing with snr=5.25 recovered every trigger while snr=4.5 -- nominally
more conservative -- lost four times as many as the default.  A lower
threshold cannot lose more triggers; a different configuration can.  The
override is monotonic by construction, which `tests/test_api.py` checks.

## The table resolves further and the realised rate does not follow

The accuracy grid was regenerated at 24000 trials a cell, four times the
previous 6000, because pycbc_inspiral_fir asks for a 1e-3 budget and the
old resolution floor was 3/6000 = 5e-4 -- a request sitting barely above
the noise. The floor is now 1.25e-4 and fd=1e-4 is answerable.

It did not help, and the way it did not help is the useful part.

    tools/score_fdr.py, 48 cases        over budget   worst
      6000 trials a cell                  15 of 48    3.06x
      24000 trials a cell                 17 of 48    4.21x

Better data scored WORSE. The old floor read every unresolved cell as
5e-4, which overstated the safe configurations and made selection pick
tighter margins than it needed. That padding was accidental, and it was
covering an optimism in the rule. Removing it exposed the bias rather than
creating it.

    realised / requested, 48 cases
      p50 0.43x   p90 2.11x   p95 3.31x   max 4.21x

So the estimate is optimistic in the tail while being twice as safe as
asked at the median. `_FDR_SAFETY` divides the budget before the margin is
placed and is the knob for that; it is left at 1.0 and overridable,
because the right value is a policy. A factor covering the tail makes the
median far safer than requested and pays escalation for it.

On the real workload it is not the tail that matters:

    pycbc_inspiral_fir, snr 5.0, fd=1e-3
      pycbc                893 triggers
      matchedfilter        885 triggers, 8.7% escalating
      safety 3             886 triggers, 10.2% escalating
      safety 10            refuses -- 1e-4 is under the table's floor

Eight triggers of 893 is 9.0e-3 against a requested 1e-3. The table
estimates 9.39e-4 for that reference at margin 1.00, from measured
neighbours at 5.4e-4 and 1.3e-3, so it is not interpolating badly between
its cells -- the cells themselves do not describe this reference. A safety
factor cannot fix a tenfold error without refusing, which is what safety
10 does.

This is the same finding recorded above in different clothes: (f, B_eff)
does not determine dismissal, and `tools/hmf_tune.py` already says the
features should be the accumulated powers at every candidate edge below
the band, not two scalars. The deeper table is shipped because it is
better data -- finer floor, fd=1e-4 answerable, same behaviour -- and the
residual is a key problem, not a resolution problem.

## The table is keyed on what the measurements say matters

The key used to be (n, band, U, K, snr, f, B_eff, margin), with B_eff
sampled as a FRACTION of the band. Two of those were wrong, and the
measurements say so directly.

**Band is not in the key.** At n=8192, f=0.99, B_eff=16, dismissal across
bands 256, 512, 1024 and 2048 -- band/B_eff from 16 to 128 -- is 1.64,
1.88, 1.77 and 1.75e-2. A 1.14x spread, inside the +-9% error bars. A
candidate band enters only through the (f, B_eff) at its own edge, which
selection computes from the reference anyway.

**n is, weakly.** Holding f, B_eff and band/B_eff fixed and moving only n,
1024 to 8192 gives 4.9x and 4.5x at the two well-measured cells. So it
cannot be factored out, but four lengths is cheap to carry.

**B_eff is sampled absolutely.** The fractional ladder tied the grid to the
variable that does not matter, and left a floor near band/10 that never
reached the values real references have.

Sensitivities on one scale, which is what sets where the measurement budget
belongs:

    margin  0.97 -> 1.00              ~90x
    f, B_eff across the grid        10-100x
    n       4096 -> 65536 (16x)       1.58x
    band    256 -> 1024               1.06x

## What the rule is now

One rule, applied the same way to both tables. Interpolate at the
reference's own (f, B_eff) -- inverse distance, in log for dismissal --
place the margin that meets the budget, price the result, take the
cheapest. Refuse when the reference has no localised peak.

The covering sets, the bracketing, the decade guard and the cost tie-break
are gone. All of them existed to make a lookup behave like a BOUND, and a
bound is not what this needs: it needs an estimate that is roughly right,
which is what the caller asked for.

## What it achieves, measured

`tools/score_fdr.py` asks the only question that matters: request a budget,
take whatever selection returns, and measure what that configuration really
dismisses. Three reference families, four lengths, two thresholds, two
budgets, 20000 trials each:

    budget    over budget   worst
    fd = 1e-2    2 of 24     1.23x
    fd = 1e-3   13 of 24     3.06x

At 1e-2 that is inside 25%. At 1e-3 it runs 2-3x, and the reason is in
`tools/uncertainty.py`: the cells that decide a 1e-3 budget carry +-35%
Poisson error at 6000 trials, and the (f, B_eff) interpolation error --
1.44x median, 3.04x p90 -- is statistically indistinguishable from that
noise. The rule is doing about as well as its inputs allow.

The obvious fix, fewer cells and more trials each, was tried: 1920 cells at
18000 trials against 5600 at 6000, the same wall clock. Cell noise improved
(+-18% from +-35%) and margin placement improved (p90 1.33x from 2.85x),
but the interpolation error grew (1.89x median, 5.03x p90) and the
end-to-end result got WORSE -- 17 of 48 over budget against 15. The finer
grid is shipped. What would actually help is more trials at the SAME
density, which is simply more machine time.

Undershoots are mostly not errors. Where the measured rate is far below the
budget the margin is already 1.000, the loosest setting there is, which
means no cheaper configuration was admissible rather than that the estimate
was wrong.

## Interpolating cost works and is still not switched on

Inverse-distance interpolation in (f, B_eff) scores 98.3% of the measured
best against the covering rule's 91.0%:

    rule                    4096@5.0 4096@6.0 8192@5.0 16384@5.5  mean
    covering (shipped)          79%      88%     100%       97%   91.0%
    pessimistic (f <= ours)     79%      71%     100%       82%   83.0%
    nearest in (f, beff)        68%      68%      93%       39%   67.0%
    interpolate in f            59%      89%     100%      100%   87.0%
    plane fit in (f, beff)     100%     100%      50%       41%   72.8%
    inverse distance (f,beff)  100%     100%      93%      100%   98.3%

Interpolating `f` alone loses to covering, which is what was measured the
first time it was tried and is explained by the isolation below: both
features carry the effect.  The interpolator matters as much as the decision
to interpolate -- a least-squares plane extrapolates past the edge of the
data and picks band 256 where the measured best is 4096, while an
inverse-distance weight is a convex combination of measured rows and cannot
return a cost below any of them.

It is still not switched on, and the reason moved rather than went away.
Priced correctly, band 256 becomes affordable and gets selected.  With the
low-B_eff rows and both guards above in place, selection takes band 256 at
margin 0.963, the table says that cell dismisses 1.45e-3, and the
FIR-search workload loses 9 of 140 -- 6.4% against a 3% budget.

So the remaining gap is not the lookup any more.  It is that the measured
cell does not predict that workload: `measure()` injects at exactly `snr`
into a template whose own power equals the reference, over the full lag
range, while the workload is broadband ratio filters on a coloured series
with per-block windows and peaks spread across a range of strengths.  Same
class of problem as the cost table's -- a number measured correctly at one
operating point and read at another -- and the same method will settle it:
vary one thing at a time between the two harnesses until the 1.45e-3 and the
6.4% meet.

Until then the covering cost rule stays.  Its pessimism about band 256 is
load-bearing for a correctness property it has nothing to do with, which is
worth knowing about any conservative default.

## The cost table is right about its rows and wrong about the query

Selection scores 90-93% of the measured best, and the obvious reading is
that the ratios are noisy.  They are not: the ratio CV is 2.4% median, 3.7%
at p90, and a regeneration that halved nothing and changed no rule scored
96.2% against the shipped table's 96.9% -- a trade, not an improvement.

At n=4096, snr 6.0 the two tables disagree about one pair, and the
disagreement is worth following because it is not noise.  Both price these
two from the same row:

    reference                                 measured K8/m0.9 : K4/m1.0
    the row they are priced from  f=0.950 beff=205.5        0.972
      what the table claims for that row                    0.960 (new)
                                                            0.985 (shipped)
    the reference actually being asked about
                                  f=0.895 beff=180.8        1.091
    a SYNTHETIC reference matched to it
                                  f=0.895 beff=183.1        1.105

So the table measures its own reference correctly, to within the CV.  What
fails is the covering rule reaching for a row that does not sit at the query.
It reaches on BOTH key axes, and isolating them -- holding one fixed and
moving the other -- says neither is redundant and neither alone is the
culprit:

    reference                       ratio   escalation K4 / K8
    query        f=0.895 beff=183   1.134      3.71% / 4.59%
    move f only  f=0.950 beff=183   1.043      0.59% / 0.68%
    move beff only f=0.895 beff=205 1.050      4.39% / 4.49%
    move both    f=0.950 beff=205   0.979      1.07% / 0.88%

Only the combination inverts the ranking, and the two act by different
mechanisms.  `f` works through the escalation rate: more power in band raises
the coarse threshold and escalation falls 6x, 3.7% to 0.6%.  `beff` barely
moves escalation at all -- 3.7% to 4.4% -- and still moves the ratio by
0.084, because B_eff is how sharp the correlation peak is and K is the number
of taps interpolating it, so a K=4 against K=8 comparison depends on it
directly.

Two things this rules out.  It is not synthetic-versus-real: make_ref at
matched features reproduces the real reference (1.105 against 1.091), so the
reference family is sound.  And it is not the cross-reference comparison the
harness restructure was built to eliminate -- both configurations here take
their cost from the same row, checked, not assumed.

The covering rule is inherited from the accuracy half, where it is right:
dismissal rises with `f`, so a row measured at least as high in both features
is the conservative one.  Cost moves the OTHER way -- more power in band
raises the coarse threshold, fewer pairs escalate, the configuration is
cheaper -- so the covering row systematically describes an easier problem
than the query.  Near a crossover between two configurations that is enough
to swap them.

Three replacements have been measured and all scored worse; see the comment
in `choose_config`.  But they were all rules over the SAME rows, and the f
ladder there is (0.713, 0.783, 0.850, 0.875, 0.922, 0.950, 0.974, 0.993) and
the cost regeneration sweeps only f in (0.85, 0.95), with B_eff at two
fractions of the band.  The next thing to try is a denser grid in BOTH
features where real references actually live -- not another rule over a grid
whose nearest row is 0.027 in f and 25 bins in B_eff away.

## Recovery factors from a mean frequency series are not a bound at coarse grids

graw1 is measured over noise realisations at a low quantile, because the
reference's autocorrelation is a MEAN shape and an individual peak can be
sharper.  g and graw are still measured deterministically from that mean shape,
and the same argument applies to them -- it just does not bite until the grid is
coarse.

Seen in a real search at snr 5.0, forcing bands the tables do not pick:

    band   kernel   trigger   triggers recovered
    2048   0.200 s     0.8%   893/893   <- what the table picks
    1024   0.144 s     1.5%   859/893   34 lost
     512   0.135 s     8.7%   885/893    8 lost

Losing more at 1024 than at 256 is not how a merely-strict margin behaves: at
R=4 the deterministic g and graw run optimistic, so the coarse threshold sits too high.
Nothing is broken today, because the table never selects those bands -- but a
smaller band at low SNR needs this fixed first.

An attempt at fixing it was wrong in two ways worth recording.  It set
g = min(g, raw_combined_recovery), which is meaningless since the interpolated
recovery is by definition at least the raw one.  And it measured the quantile
against a synthetic realisation with an arbitrary noise level, so the number it
produced was not a bound at all.  Together they took the trigger rate from 0.8%
to 25% and the kernel 2.4x slower at the band actually in use.  A real fix has
to model the realisation spread from the data, not from a chosen constant.

## Bracketing the odd transform

The odd pass costs a full m-point transform and runs on about half of all
pairs, for 28% of the filter's time.  It cannot be *replaced* -- see the next
section -- but it can be *avoided* most of the time, without changing a single
reported trigger.

The idea is to bound the combined maximum rather than compute it. An
interpolated statistic S, built from the even series alone, satisfies
`lo <= S/comb <= hi` for measured bounds. Then

    max(ev_max, S/hi) >= tc   ->  fire; the odd pass cannot change the verdict
    S/lo              <  tc   ->  reject; likewise
    otherwise                 ->  run the odd transform and decide exactly

Output is bit-identical because every case the bracket cannot settle is still
settled by the transform.  `ev_max <= comb` holds exactly, so it tightens the
lower bound for free; the current code does not use it.

S is the largest of the even maximum and a least-squares interpolation
evaluated at half-sample offsets around the top C even samples.  Two
measurements set C and the kernel length:

- **C=32 suffices.** The rank of the odd maximum's best even neighbour is 0 at
  the median, 13 at the 99th percentile and 26 at worst over 1150 pairs. C=16
  covers 99.3%, C=32 covers all of them. An earlier attempt stopped at C=16
  and concluded the route was closed.
- **9 taps is the optimum**, not because it is accurate but because the total
  cost is interpolation plus the ambiguous fraction, and longer kernels buy
  less bracket than they cost. Measured at the operating point:

| taps | cands | interp | ambiguous | total | odd pass |
|---:|---:|---:|---:|---:|---|
| 5 | 16 | 0.025 | 0.233 | 0.258 | 3.87x cheaper |
| **9** | **16** | **0.045** | **0.141** | **0.186** | **5.37x cheaper** |
| 17 | 16 | 0.085 | 0.114 | 0.199 | 5.02x cheaper |
| 17 | 32 | 0.171 | 0.085 | 0.256 | 3.91x cheaper |
| 33 | 32 | 0.331 | 0.076 | 0.407 | 2.45x cheaper |

Bounds derived on six captured segments and tested on the other six violate at
0.188%, so they need a safety margin and fixture validation, exactly as the
even-pass threshold's does. Only the lower bound is dangerous: an over-report fires the
coarse margin spuriously, which costs a reconstruction and cannot invent a
trigger, while an under-report past the bound loses one.

Projected: the odd pass falls to 0.18 of its cost, the filter from 14.77 to
11.4 ms per segment and 2.51x to 3.25x, with the same triggers.

## Why the odd transform is not replaceable by evaluating a few points

The odd pass exists only to find the peak between even samples, and it costs a
full m-point transform. Evaluating a handful of points instead looks obviously
cheaper. It is not, and the reason is not what it first appears.

An exact value at a half-sample offset is one Goertzel evaluation: m complex
multiply-adds, about 8200 flops at m=1024. The odd transform costs
(m/2) log2(m) butterflies, about 51000, and returns all m values. So sparse
evaluation wins below roughly six points, and the whole question is how few
candidate locations suffice.

Measured with exact values and no interpolation kernel at all, over 2280 real
pairs, taking the odd samples adjacent to the largest even samples:

| candidates | median | 1st pct | worst |
|---:|---:|---:|---:|
| 3 (break-even) | 1.0000 | 0.9171 | 0.7903 |
| 8 | 1.0000 | 0.9639 | 0.8675 |
| 16 | 1.0000 | 1.0000 | 0.9258 |

The odd maximum is not located near the large even samples. Sixteen exact
evaluations cost five times the whole transform and still leave a worst case
of 0.926, against the 0.897 the even-pass threshold already achieves for free. The
candidate set cannot be narrowed, so nearly everything must be evaluated, and
an FFT is the efficient way to evaluate everything.

The other half of the argument is that no kernel can close the gap either,
and this is worth stating because designing one is not the same as truncating
one. Solving directly for the best K-tap filter -- weighted least squares over
the measured spectral weight, which is available because m and the weighting
are both known -- beats truncating the ideal kernel by about a factor of two
at every length:

| taps | truncated ideal | least squares |
|---:|---:|---:|
| 5 | 1.9e-01 | 8.8e-02 |
| 9 | 9.5e-02 | 5.6e-02 |
| 17 | 8.3e-02 | 3.2e-02 |
| 33 | 4.2e-02 | 2.6e-02 |

(worst error relative to the peak.) It is not enough. Computing all m
half-sample points with a K-tap filter costs m*K*8 flops against the
transform's 51000, so the transform's effective budget is fewer than 6.2 taps
per point, and the best possible five-tap filter still carries 8.8% error.
Fractional delay on a critically sampled signal needs length, and the coarse
series occupies every one of its m bins by construction -- the band IS the
transform size, so there is no oversampling headroom for a short delay filter
to live in.

So the transform is not merely convenient here, it is close to optimal: it
produces every half-sample point at an effective six taps each, which no
filter can match.

Two earlier attempts to settle this reached the same conclusion for wrong
reasons, and both are worth recording as traps:

- **A plain sinc is the wrong kernel here.** The coarse band is one-sided, so
  the exact interpolator carries a carrier phase,
  `K(y) = exp(i pi y (m-1)/m) sin(pi y) / (m sin(pi y/m))`. A plain sinc gives
  65% error even at full length while passing every check made at integer
  samples.
- **A short truncation of that kernel is not interpolation.** The band is a
  rectangle, so the kernel decays as 1/y and truncation error falls only as
  1/K. A nine-tap version appeared to work well -- worst case 0.946 on one
  segment -- because it overshoots rather than because it is accurate; its
  median recovery is 1.02, above the true grid maximum. Across all twelve
  captured segments its worst case is 0.919, needing a 1.088 bias, and the
  apparent accuracy was an artifact.

## Other structural routes measured and rejected

Per-pair only; nothing here relates one template to another.

- **A third rung on band.** A band-512 statistic, biased up by its worst-case
  ratio to the band-1024 one (0.792, so a 1.26 bias), rejects 52% of pairs at
  0.45 of the cost: net 1.08x at the operating point. At a 1% trigger rate it
  would be 1.44x, so it is a function of where the coarse threshold sits rather than a
  property of the method.
- **A pre-test with no transform at all.** The only O(m) bound available from
  the spectrum is Parseval, `max <= sqrt(m) ||P||`, which is loose by
  `sqrt(m / ln m)`, about 12x at m=1024. Nothing to margin on.
- **Stage-A partial results.** Parseval along the k1 axis gives the energy of
  each residue class of lags for free once stage A is done, but that sums one
  signal lag against N1 noise lags: it rejects 20% of noise pairs and saves
  only stage B on those.

## The bracket

The odd coarse transform exists to find peaks that fall between the even pass's
grid samples. It runs on the ~27% of pairs that clear the even-pass threshold, and for
most of them the answer is already determined: the even series can be
interpolated to a statistic `S` whose ratio to the true combined maximum is
bounded on both sides, and a bracket that does not straddle the coarse threshold settles
the pair without the second transform.

This was implemented, measured 5x slower, and left off behind `MF_BRACKET=1`
for a long time. Five separate diagnoses failed to explain it -- compilation
unit, an inner-loop branch hoisted to a template, 4K aliasing, the low-threshold
peak-update branch, an in-place read of the output buffer. None of them was the
cause.

The cause was that the fast path was dead code. `interp_max` exists twice: a
vectorised one in `balanced-inl.h`, compiled once per SIMD target, whose own
comment says it lives there because the scalar version "ran scalar there,
costing more than the transform it saves"; and a scalar one in `matchfilt.c`,
which is built at the **baseline ISA** so the library can be loaded before the
CPU is interrogated. The vectorised one was fully plumbed -- exported in the
back-end vtable, wrapped as `ap_interp_max` in `dispatch.c`, declared in
`transform.h` -- and never called. The call site used the baseline one, which
walks every lag scalar while maintaining a top-16 list with an O(n) rescan on
each improvement.

Measured per pair, at band 1024:

| | even | odd | net |
|---|---:|---:|---:|
| bracket off | 2114 | 540 | -- |
| bracket on, scalar scan | 10410 | 420 | +8350 |
| bracket on, vectorised | 2188 | 294 | -172 |

With that fixed, the bracket has been turned on and off three times. It is
off. This is the evidence.

The reject branch fires when `S/ilo < raw_thr`. A wrong rejection only loses a
trigger above the coarse threshold, and `raw_thr = graw * margin`, so the branch is sound
while

    ilo <= min(S / true) / graw

over real triggers. `MF_BRACKET=2` computes the statistic without acting on it,
so that minimum can be measured on every pair rather than on the ones the
bracket happened to leave behind. It saturates with tap count:

| taps | `HMF_IK` | min S/true over real triggers | sound `ilo` |
|---|---|---:|---:|
| 9 | 4 | 0.8384 | 0.8636 |
| 13 | 6 | 0.8855 | **0.9121** |
| 17 | 8 | 0.8931 | 0.9199 |
| 21 | 10 | 0.8931 | 0.9199 |

17 and 21 tie, which says the limit is the design criterion and not the length:
the taps are a weighted least-squares fit, which minimises mean error and does
nothing about the tail. At `ilo=0.90`, inside the 13-tap bound, the bracket is
a ~2% win on the captures with 31/842 and 0/842 unchanged.

**It then lost a trigger on the first independent workload it met.** The
`pycbc_inspiral_fir` example at threshold 5.0 returns 893 triggers with the
bracket off and 892 with it on, and its kernel is 4% *slower* with it on
(0.229 s against 0.220 s). The bound was derived from one dataset and does not
transfer. Backing `ilo` off to 0.86 -- conservative enough to be safe on both
-- makes it a loss on the captures as well (10.63 ms against 10.14). There is
no setting that is both safe and profitable, so it stays off.

It does help where the trigger rate is low: at threshold 5.5 the same example
gives 0.084 s with it on against 0.089 s off, with the same 60 triggers. A
caller who knows their operating point can turn it on with `MF_BRACKET=1`.

What the exercise bought is a correct implementation -- the vectorised
`interp_max` it depends on was dead code, which is why it used to measure 5x
slower -- and a derived soundness criterion in place of a fitted constant.

Two knobs matter and they are not symmetric:Two knobs matter and they are not symmetric:Two knobs matter and they are not symmetric:

- **`MF_IFRAC`** (0.95) is the candidate cut, as a fraction of the grid maximum.
  Below ~0.79, the band's worst-case recovery, the cut is provably free. 0.95
  is past that and empirical: it costs a third of the pass and settles just as
  many pairs, because the candidate that decides is the maximum and its
  neighbours. Miss count is flat from 0.75 to 0.99.
- **`MF_BRACKET_LO`** (0.90) is the reject side, and it is the one that can cost
  a trigger, because an under-estimated `S` rejects a pair that should have
  fired. It does not tolerate tuning: 0.90 misses 31/842 -- identical to the
  bracket being off -- while 0.93 misses 34 and 0.97 misses 51. The fire side
  (`MF_BRACKET_HI`, 1.10) is safe in the other direction and barely matters,
  since fires are 0.9% of pairs against 11.4% rejects.

`HMF_IK` is 6 rather than 4 so that a caller who enables the bracket with the
default `ilo` gets a sound configuration rather than a fast one.

## Batch shape

D data segments against T templates is a symmetric product: the pair loop
tiles both axes, so a 24x16 batch and a 16x24 one cost the same to within a
percent. What is *not* symmetric is a degenerate shape -- one segment against a
large bank makes the even coarse pass stream the whole coarse bank for T pairs
and reuse none of it. `run_series` therefore groups blocks that share a window,
the group breaking at the ragged windows at a segment's edges.

The group size was briefly chosen from whether the coarse bank still fitted L2
(32 above, 4 below). That was right for the code it was measured on, where
every block also paid to ingest a full spectrum it almost never used, and
grouping was amortising that. Once the ingest became lazy the cache effect went
with it and a large group is now only a cost:

| templates | g1 | g4 | g8 | g16 | g32 |
|---|---:|---:|---:|---:|---:|
| 37 | 1.149 | 1.136 | **1.126** | 1.134 | 1.142 |
| 74 | 1.133 | **1.087** | 1.092 | 1.126 | 1.119 |
| 128 | 1.104 | 1.056 | **1.049** | 1.131 | 1.132 |
| 256 | 1.209 | 1.146 | **1.117** | 1.125 | 1.120 |
| 418 | 1.180 | **1.119** | 1.153 | 1.165 | 1.190 |

8 is best or within a percent of it everywhere, so it is a constant.
`MF_DGROUP` overrides it, and `tests/test_api.py` pins the result to be
identical across group sizes -- this is an arrangement decision, not an
approximation.

## The spectrum a block almost never needs

Every pair reads the coarse band. The *full* spectrum is read only when a pair
fires -- 1.5% of pairs at threshold 5.0 and 0.11% at 5.5, so roughly 42% and 4%
of blocks. `run_series` nonetheless ingested it into the full plan for every
block, splitting 2n interleaved floats into the kernel's SoA layout.

Nothing needed it to be eager. `ap_hmf_run` has always had a lazy path guarded
by `dready`, used when a caller supplies spectra directly. What forced the eager
call was a single staging buffer: `set_data` retains the caller's pointer, and
the next block overwrote it. Giving the group one buffer per slot -- `dgroup *
2n` floats, 256 KiB at n=4096 -- removes the aliasing and lets the lazy path do
the work only for blocks that fire.

Worth 43.84 -> 41.79 us/block at threshold 5.0 and 34.89 -> 33.61 at 5.5. End
to end that is 11.05 -> 10.50 ms/segment (3.38x -> 3.56x) at the default margin
and 14.77 -> 13.75 (2.54x -> 2.67x) at the zero-loss margin, with 31/842 and
0/842 unchanged.

Two things deliberately stay per-segment. The odd coarse transform runs on one
pair at a time because only ~27% of pairs reach it, and the full reconstruction
because only ~1.5% do: both are sparse scatters over the D x T rectangle, and
batching a rectangle around a sparse set would run the transform for every
`(d, t)` in its hull. The even pass, which every pair pays for, is the one that
is batched.

The pair-loop tile is a separate knob (`MF_MFTILE`, default 8). A sweep over
4/8/16/32/64 at five shapes put 8 within 5% of the best everywhere and found no
rule that beat it -- the optimum wanders between 8, 16 and 64 with no monotone
dependence on either axis -- so it is left fixed rather than fitted to noise.

## The tuning table

The band, oversample and tap count used to come from `hmf_choose`, a
nearest-neighbour lookup on `(n, snr, fd)` that never saw the signal. They now
come from two measured tables, `python/matchedfilter/accuracy.txt` and
`cost.txt`, shipped as package data and read once when the plan is built.

**Which table, for which device.** Cost is a property of the machine and is
resolved per architecture — `cost-gfx11.txt` and so on, falling back to the
shipped generic one. Accuracy is a property of the *algorithm*, and one
table served every device for a long time on the grounds that the algorithm
is the same everywhere. It is not: where the CPU interpolates the coarse
peak, the GPU escalates the whole interpolation window, so it refines a
superset of the CPU's pairs.

Sharing the table is safe only in that direction. A superset can dismiss
only less, so the CPU's measured rate is an upper bound for the GPU, which
over-keeps the promise — measured, the CPU omits about 1.5% against a 1%
budget and the GPU omits nothing. It is also leaving speed unclaimed,
because it is calibrated for an algorithm more aggressive than the one it
runs.

That is an argument, not a guarantee, so it is resolved rather than
assumed. `accuracy_table_for` looks for `accuracy-<backend>.txt`, then
`accuracy-gpu.txt`, then the default, and
`test_the_gpu_is_no_less_conservative_than_the_cpu` runs both paths over
the same noise realisations and fails the moment the GPU dismisses anything
the CPU keeps. When that happens the argument is void and the GPU needs
rows of its own; there is now somewhere to put them.

**What it is keyed on.** Two numbers per candidate band, both computed from
the caller's reference:

- **f(m)** -- the accumulated power below that band edge, how much signal the
  band keeps;
- **B_eff(m)** -- the effective bandwidth of the power *inside* it, as the
  participation ratio `(sum p)^2 / sum p^2` in bins, which sets how sharp the
  correlation peak is and therefore how badly the coarse lag grid scallops it.

One number does not suffice: two references agreeing on f(512) to four figures
differ threefold in dismissal when their in-band power is distributed
differently -- 85% below bin 256 against 95%. The extremes make the mechanism
plain: all the power in one bin is `B_eff = 1`, a maximally wide peak the grid
resolves perfectly; flat across the band is `B_eff = m` and a peak one sample
wide. Both features move dismissal the same way, so the row that speaks for a
reference is one measured at least as high in both.

**How it was measured.** By running the real filter, not a model -- an earlier
attempt re-derived the statistic in numpy and reported a dismissal of 0.0 for a
configuration that triggers 60% of the time. The two halves need *different*
workloads, which is the subtlety:

| | workload | why |
|---|---|---|
| FDR rows | injections at the threshold | you cannot count dismissals without signals |
| COST rows | pure noise at the threshold | cost is set by how often the coarse pass escalates, which on real data is ~1% |

Timing on the injected harness made every band read 9-13 us/pair, because
injections force half the pairs to fire whatever the band. On noise the same
cells separate 12.7 us/pair from 1.8.

**What it delivers.** Asked for `fd=1e-3` on the twelve captures it returns
**0 of 842**, against the old compiled default's 31 of 842 -- 3.7% missed on a
0.1% budget. The guarantee is the thing being bought.

It also now buys back most of the cost. The margin scaling is a fourth selected
dimension rather than a hand-set constant, and the cost rows are relative
measurements taken against a pivot on a common reference, so configurations
are actually comparable. Together those moved the pick from band 512 at
margin 0.90 -- the slowest of the four admissible options, 0.082 ms/block -- to
band 2048 at margin 1.00 at 0.065, 21% cheaper at unchanged accuracy.

The cheapest admissible row is not always the cheapest thing that works on a
given dataset. Band 1024 at margin 0.94 measures 0.053 ms/block and misses
nothing on the captures, but its measured dismissal is 1.3e-3 against a 1e-3
budget, so it is declined. That is the right call and worth being explicit
about: 67 triggers cannot resolve 1e-3, so the captures agreeing is not
evidence, and the table is the only instrument here that sees that far down.
A caller who wants it can ask for `fd=2e-3` and get it.

**Regenerating.** `tools/hmf_tune.py`. The two halves go stale independently:
COST on any kernel or machine change, FDR on any change to the coarse threshold or the
interpolation. The file carries its CPU, commit, trial count and resolution
floor, and `MF_TUNING` points at a different one -- so retuning needs no
rebuild.

### Retuning for your hardware

The two tables are separate files because they are different kinds of thing.
`accuracy.txt` is a property of the ALGORITHM -- the same numbers hold on any
machine running the same build. `cost.txt` is wall time on one CPU. Only the
second is worth regenerating locally, and doing so cannot touch the first:

```
python tools/hmf_tune.py --retune-cost --out mycost.txt
export MF_COST=$PWD/mycost.txt
```

It re-measures the timings at the cells the shipped accuracy table already
covers. A few minutes on a many-core box; it parallelises over cells, which is
safe precisely because the numbers are ratios -- every configuration in a pass
is timed against a pivot in that same pass, so contention is common to all of
them and cancels. Measuring under contention is in any case the condition most
deployments run in.
`MF_ACCURACY` overrides the other half if you ever need to.

The accuracy table should not normally need regenerating -- they describe the
statistic, not the machine, so they travel. Regenerate them if you change the
margin, the recovery factors, the interpolation taps or the oversampled grid,
since those change what is being measured:

```
python tools/hmf_tune.py --n 4096 --snr 5.0 --fd 1e-3 --trials 20000
```

Budget ~10^5 detections a cell to resolve `fd = 1e-4`; the shipped table is at
2x10^4 trials and resolves about 3e-4. Both halves are plain text and the file
records the CPU, the commit and the trial count it was made at, so a stale
table is identifiable rather than merely wrong.
