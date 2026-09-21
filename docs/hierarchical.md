# The hierarchical matched filter

The hierarchical filter assumes that enough of a template's signal-to-noise
sits in the low part of its band for a narrow slice to bound the full result.
Where that holds, it correlates only that slice, on a coarse lag grid, and pays
for the full correlation only where the coarse result could still become a
detection.  Where it does not hold -- power spread flat across the band, or
concentrated high -- the slice bounds nothing useful and the pre-pass is added
cost with no saving.

The guarantee is deliberately one-sided.  Every peak it reports is
**bit-identical** to `ap_mf_run`'s, because when the gate fires it *is*
`ap_mf_run`.  It never invents a peak and never shifts one.  What it can do is
miss one, with probability at most `fd` for a signal of strength `snr`.

## Where the speedup comes from

    cost  =  coarse transform  +  gate scan  +  trigger rate x full correlation

The trigger rate is the whole game.  It falls off as `exp(-t_c^2/2)` per coarse
sample, so a gate threshold a few tenths higher is worth more than any amount of
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
- **The gate only needs `|v|`**, and the re-modulation phase has unit magnitude,
  so it cancels.  demodulate -> interpolate -> re-modulate collapses into one
  complex tap `w_k * exp(i pi (d-k)/U)` applied to the raw series.

Because the fine grid is an exact integer subdivision of the coarse one, the tap
bank needs `HMF_NSUB` rows rather than the ~1024 a general resampler would: a few
hundred bytes, L1-resident, effectively a polyphase bank.

## Calibrating the gate

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

## Known limits

- **The coarse transform cannot go below 256 points**, because that is matchedfilter's
  smallest supported size.  The unconstrained design often wants 64 or 128, so
  supporting smaller transforms would unlock more speedup, particularly at
  N=2^11 and high SNR.
- **The gate is per pair, not per bin.**  The transform is global, so a partial
  one would not help; but it means a single loud bin drags the whole pair
  through the full correlation.
- **The trigger rate depends on the data.**  On noisier data than the design
  assumed the gate opens more often, and at a high enough rate the coarse pass
  is pure overhead.  `ap_hmf_stats` reports it; that is the first number to look
  at when the filter is slower than expected.

## Measured

One core of a Zen 5, AVX-512, D=T=16, bin n/4, whole record searched.  Per pair,
against the ordinary filter on the same inputs.

    pure noise - the gate should stay shut
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
that combination forces `t_c` low enough that the gate opens on noise alone.
`ap_hmf_stats` exists so this is visible rather than mysterious.

The measured speedups on noise (1.95-3.57x) sit below the design model's
prediction (~4.7x at 2^11).  The model costs the coarse pass in flops, and small
transforms do not hit their flop bound - this is the gap between 5*m*log2(m) and
what a 256-point transform actually costs.

## A scan that was conservative and still wrong

The first working version interpolated around every sample that passed the cheap
pre-gate.  That is *safe* - strictly more places checked than the calibration
assumes, so it can never lose a detection - and it measured **0.08x**, twelve
times slower than the plain filter it was meant to beat.

The cause is worth remembering because it is invisible in the design model.  The
benchmark template has f = 0.994: its power is so concentrated that the
correlation peak is *broad*.  A broad peak's shoulder sits between `graw*gate`
and `gate` for ~100 consecutive samples, and each one paid 14 interpolations -
1360 per pair where 14 suffice.

The fix is also what makes the code match its own calibration.  `recovery()`
measures the interpolated maximum **around the global argmax**, so the scan
should do exactly that: one running-maximum pass with no sqrt and no branches,
then interpolate only around the winner, and only when the raw maximum lands in
`[graw*gate, gate)`.  Interpolations per pair fell from 1360 to 2.1 and the
worst case from 0.08x to 0.79x.

The general lesson: a gate that is conservative in the *statistical* sense can
still be catastrophic in the *computational* sense, and the test suite will not
notice, because conservative gating produces correct answers.  Only the
benchmark catches it, and only on data whose peak shape differs from the design
template's.

## Open: the gate does not behave as modelled at large N

At 2^18 and 2^20 the measured trigger rate disagrees with the design model, and
the disagreement is in the unsafe direction.

      n      model                        measured
    2^18   t_c=4.93, trig 50.4%, 1.04x    trig 0.0%, 5.01x
    2^20   t_c=1.32, trig  100%, 1.00x    trig 0.0%, 2933x

The model is the one to believe here.  The gate sits below the detection
threshold by construction, and with ~10^6 lags the coarse maximum in pure noise
reaches about sqrt(2 ln G) ~ 3.7 -- far above a gate of ~1.5.  Essentially every
pair should trigger.  A measured 0% means the run-time gate is much higher than
the calibration intends, and **a gate that is too high dismisses real signals
silently**.  Reported peaks stay bit-identical either way, so the test suite
cannot see this; only the trigger rate can.

Traced so far: the template's band fraction at 2^20 really is f=0.427, which
after the f_eff clamp should give t_c ~ 1.55 and fire on almost every pair.  The
C path does not do that and the cause is not yet found.

Two things this also makes clear, independent of the bug:

- **A realistic threshold at large N is not 5.5.**  The full filter alone
  expects n*exp(-t^2/2) noise crossings per pair - about 0.3 at 2^20 and t=5.5 -
  so a real search would set the threshold from the trials factor.  The
  hierarchical gate's usefulness depends on the margin between that threshold
  and sqrt(2 ln G), which shrinks as N grows.
- **The gate is per pair, not per bin.**  The output is one peak per bin, but
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
reported peak, only the gate decision.

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
and re-validate it, because a half-finished gate that is slightly wrong looks
*faster*, and the correctness suite cannot see it.

## Recovery factors from a mean spectrum are not a bound at coarse grids

graw1 is measured over noise realisations at a low quantile, because the
reference's autocorrelation is a MEAN shape and an individual peak can be
sharper.  g and graw are still measured deterministically from that mean shape,
and the same argument applies to them -- it just does not bite until the grid is
coarse.

Seen in a real search at snr 5.0, forcing bands the design table does not pick:

    band   kernel   trigger   triggers recovered
    2048   0.200 s     0.8%   893/893   <- what the table picks
    1024   0.144 s     1.5%   859/893   34 lost
     512   0.135 s     8.7%   885/893    8 lost

Losing more at 1024 than at 256 is not how a merely-strict gate behaves: at
R=4 the deterministic g and graw run optimistic, so the gate sits too high.
Nothing is broken today, because the table never selects those bands -- but a
smaller band at low SNR needs this fixed first.

An attempt at fixing it was wrong in two ways worth recording.  It set
g = min(g, raw_combined_recovery), which is meaningless since the interpolated
recovery is by definition at least the raw one.  And it measured the quantile
against a synthetic realisation with an arbitrary noise level, so the number it
produced was not a bound at all.  Together they took the trigger rate from 0.8%
to 25% and the kernel 2.4x slower at the band actually in use.  A real fix has
to model the realisation spread from the data, not from a chosen constant.
