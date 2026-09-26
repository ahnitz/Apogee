# CPU dispatch and tool cleanup, 2026-09-26

The matchedfilter library computes binned complex correlation peaks for batches
of data and templates. Its hierarchical path saves work by rejecting pairs in
a cheaper coarse stage, then computes surviving peaks with the full filter.
Reported survivors must keep the flat filter's index and complex value;
false-dismissal budgets and configuration costs are separate concerns.

## Completed

* Adaptive x86 pair batching at sizes 256/512/1024; see
  [measurements and dispatch limits](cpu-plan.md#pair-batching-at-2561024-adaptive-dispatch).
  SWAR is deferred. The GPU SoA draft remains experimental.
* [The 2D cache-tile diagram](assets/pair-tiles.svg) distinguishes operand reuse
  from SIMD lane occupancy.
* `score_selection.py` now uses the library's admission candidates and current
  `(band, taps)` configuration. It reports unsupported legacy accuracy coverage
  explicitly. `score_cost_rule.py` can be imported without running benchmarks.
* `hmf_tune.py` starts only after defining its helpers; regeneration parses
  ACC/ACC2/ACC2R correctly and measures relative costs on shared references.
  It includes bands 64/128. U=2 remains a compatibility column, not a selectable
  oversampling mode. `jobs`/`trials` are retained by `retune_cost` for old callers;
  cost timing is serial and interleaved, not injection-count based.
* `hier_bench.py` uses the current two-array raw result and checks replayed
  complex values against flat results. `hier_all.sh` uses `PY` or `python3`,
  quotes fixture paths, rejects missing captures and propagates failures.
* The cross-device series test now distinguishes independently tuned gates
  from execution correctness. Automatic gates may omit different triggers;
  every survivor must match flat. With an explicit open gate both devices must
  report the same complete set and complex values. This fixes the invalid
  assumption in the supplied macOS failure; actual Metal execution still needs
  macOS CI.

## Reproduce

```sh
python tools/bench_pairbatch.py
python tools/bench_pairbatch.py --include-ingest
MF_ISA=AVX2 python -m pytest -q tests/test_pairbatch_policy.py
MF_ISA=SSE4 python -m pytest -q tests/test_pairbatch_policy.py
python tools/score_selection.py --n 4096 --snr 6
python tools/hmf_tune.py --retune-cost path/to/accuracy.txt --out /tmp/cost.txt
FIXTURES=/path/to/captures PY=python3 BAND=2048 bash tools/hier_all.sh
```

Full-table regeneration can be expensive. A small accuracy file containing the
cells of interest is supported; do not treat sparse timing rows as universal
coverage. Keep the generated output separate until selection is validated.

## Measured limits and remaining work

The twelve local PyCBC captures contain 842 flat peaks. Their pinned band-1024
configuration misses three captured triggers, with both forced-balanced and
automatic CPU execution. Band 2048 reproduces every captured trigger in all
twelve segments.

**Followed up and resolved: this is not a dismissal-calibration defect.** It
was recorded here as one, and measuring it properly says otherwise. Two
things were missing. First, the pinned band understates it -- selection picks
band 512 for this reference, and band 512 loses 20 of 842, not 3. Second,
and decisive, those are NOISE triggers. The budget is a promise about
signals, and on the same captures with the same plans, 2400 injections at
snr 5.2 were dismissed ZERO times at bands 256, 512 and 1024, a resolution
of 4.2e-4 against a 1e-3 budget.

    band   flat noise triggers dismissed     injections dismissed
     256      48  5.7e-2                        0 of 2400
     512      20  2.4e-2                        0
    1024       3  3.6e-3                        0
    2048       0  0                             --  (f = 1.0000)

Marginal noise triggers are preferentially gated because their in-band part
is an independent draw, where a signal's is fixed by the template. Band 2048
has f = 1.0 and loses nothing, which is the mechanism check. See
docs/hierarchical.md and tests/test_gate_population.py, which asserts both
halves so the noise loss cannot be read as a budget violation and "fixed" by
lowering the gate.

Still open from this: a bank that does not match its reference. A synthetic
bank spanning exponents -7/3 to -4/3 against a reference at -7/3 omits 66 of
508 injections at band 512, 130x the budget -- while the captured 37-template
bank, whose spread is wider, passes. The complete 483-template PyCBC search
is still not validated.

`tools/cost-small-bands-4096-experimental.txt` records current-runtime relative
costs at n=4096, SNR 5/5.5/6/6.5, reference anchor fractions .9/.99 and bandwidths
8/32. Every anchor from 64 to 2048 was timed with K=4/8, batch=64, 16 templates,
four rounds, pivot band1024/K8, on Ryzen AI Max+ 395 AVX3. These rows are **not
installed as defaults**: appending their 64/128 rows made the sparse lookup
select band128/K4 on the inspiral reference, measuring 4.37× over flat versus
10.75× for band512/K4 in that run.

**Followed up: that is a symptom, and the cause is a CORRECTNESS defect, not a
performance one.** Band 128 at the reference it was picked for dismisses
2.9e-2 of INJECTED SIGNALS against a 1e-3 budget. It should never have been
admissible, and enabling the cost rows would have shipped a gate that misses
its promise.

Two separate things were wrong with the original diagnosis. The cost rows
themselves are measured at reference anchors of B_eff 8 to 40, while real
references query at 45 to 225 -- so every small-band lookup extrapolates,
which is the same mistake ACC2 made and ACC2R was created to fix. But fixing
that alone would not help, because the accuracy side admits band 128 anyway.

The real limit is narrower than "small bands are bad":

    band   f       ratio   table thr   injections dismissed
     128   0.6970   1.24      3.3341    15 of 523 = 2.9e-2   <-- over
     128   0.9476   2.68      3.9209     0 of 533
     128   0.9858   6.60      4.3348     1 of 550
     256   0.8832   1.66      3.5307     0 of 523

Band 128 is sound everywhere except the low-ratio corner. Dropping its
threshold 10%, to 3.0007, takes dismissal to 0 of 605 -- so the table row is
about 11% too high, not the band unusable. `ratio` is band/B_eff and the
table is keyed on it because band is supposed to drop out; near the grid edge
it does not. The grid starts at ratio 1.200, the failing query is 1.24, and a
query at 1.37 (f = 0.695, band 1024) passes.

Bisecting the table against measurement (`tools/audit_threshold.py`, which
deliberately does NOT reuse `hmf_tune.measure_tc` -- a check sharing the
producer's setup cannot see a fault in it) says the error is a GRADIENT, not
one bad cell:

    band   f       ratio   measured safe   table    table is
     128   0.6970   1.24       2.8956      3.3341   15.1% HIGH
     256   0.8832   1.66       3.3843      3.5307    4.3% high
     512   0.9584   2.83       3.8774      4.0354    4.1% high
    1024   0.9882   5.33       4.3502      4.2423    2.5% low

At ratio 5 and up the table is correct or conservative. Below it the rows
are a few percent optimistic -- bands 256 and 512, which selection ships,
run 4% hot and pass only because they have slack -- and by ratio 1.24 the
error reaches 15% and breaks through into real dismissals.

**The cause is the table's KEY, not its rows.** It is keyed on
(n, f, ratio, snr, fd), and band is left out on the argument that samples
across the peak is band/B_eff with no band in it. Measured at a fixed
(f = 0.70, ratio = 1.20), n=4096 snr 5.0 fd 1e-3, realising that ratio at
four bands: 2.8078, 2.9797, 3.1000, 3.2719 for bands 128, 256, 512, 1024 --
**16.5% across band alone**. The rows are all measured at
max(256, min(1024, n//4)), which is 1024 at n=4096, so a query at a smaller
band gets a threshold calibrated for a larger one.

It is the coarse maximum: the statistic is a max over `band` lags and the
max of N draws grows like sqrt(2 ln N), so the threshold goes as
sqrt(ln band). Across 20 cells at five different (f, ratio, snr, n) that
law fits to 2.3% mean and 8.8% worst.

An earlier entry here blamed the producer's trial count -- 6000 a bisection
step expects 6 events at fd=1e-3 -- and a re-measurement appeared to confirm
it. It did not. That re-measurement ran at band n//8 while the shipped rows
are at n//4, and the apparent error was the band mismatch. Corrected for
band the shipped rows are -1.8% mean at fd=1e-3 and -4.6% at fd=1e-2, i.e.
sound. The trial count is a real weakness in the producer and is not what
ails the table.

**Applying the sqrt(ln band) correction at lookup is NOT the fix**, and that
is measured rather than argued. On pure noise at n=4096, correcting the
bands selection actually uses:

    band   escalation table -> corrected   time
     256        37.5% -> 84.4%             2.13x SLOWER
     512         7.8% -> 21.9%             1.88x SLOWER
    1024         9.4% -> 9.4%              unchanged

It would cost about half the hierarchical speedup to fix a 4% margin that
produces no measurable dismissals -- bands 256 and 512 dismiss 0 of 523
injections today. The correction is too coarse: it is conservative by 6.7%
at band 256, and that 6.7% is what costs 2.13x.

So the fix is rows measured AT the band being queried -- a third key --
which is why tools/regen/threshold_lowratio.py takes --band as a sweep.
`tools/threshold-by-band-4096-experimental.txt` is that sweep, 59 rows over
14 (f, ratio) cells at four bands, and it shows the structure:

    f      ratio   128    256    512   1024    spread
    0.60   1.20   2.891  3.087  3.239  3.465   19.9%
    0.70   1.20   3.058  3.168  3.311  3.547   16.0%
    0.80   1.20   3.208  3.321  3.369  3.578   11.6%
    0.90   1.20   3.339  3.438  3.471  3.670    9.9%
    0.95   1.50   3.599  3.691  3.727  3.763    4.6%
    0.995  1.50   3.732  3.824  3.830  3.849    3.1%

The spread is ordered by f, and that is the useful part: band matters most
where the band keeps LEAST of the signal. At f=0.60 it is worth 20%; by
f=0.995 it is 3%, which is measurement noise -- and that last claim is now
measured rather than asserted. One cell re-run under eight seeds gives
sd 1.0-1.3% and a full range 2.5-3.8% (`audit_threshold.py --repeat 8`),
so 19.9% is about twenty sigma and 3.1% is indistinguishable from a re-run.
Against that floor, ratio 1.20 clears it at every f measured, and ratio 1.50
clears it down to f=0.95. Keying band out would therefore only be safe for
f >= 0.98 and ratio >= 1.5 -- a corner -- so the third key does not get
cheaper by exempting high f. The coarse statistic is a max
over `band` lags so its noise floor grows as sqrt(2 ln band), and when f is
near 1 the signal dominates that floor and band stops mattering.

**That is why both shipped tables could key band out and look correct.**
threshold.txt is measured at one band per n and is right AT that band.
accuracy.txt justifies the same omission with a 1.14x spread measured, in
its own header's words, "across band/B_eff from 16 to 128" -- every cell of
that check sits at ratio >= 16, where band genuinely does not matter. Real
references run at ratio 1.3 to 5.3. Both tables validated the omission
outside the operating range, and accuracy.txt needs the same treatment as
threshold.txt before small bands can be selected.

Selection cannot reach the corner today: over 352 sampled (n, reference, snr,
fd) combinations the lowest ratio it picks is 1.29 at f = 0.787, which
measures 0 of 598. tests/test_low_ratio_corner.py pins all three facts --
the corner fails, band 128 is fine away from it, and selection stays clear --
so the cost rows cannot be installed without meeting this first. More representative reference/batch coverage and validation of the
cost lookup are required before enabling those bands automatically. Explicit
band=64/128 remains supported and tested.

Lazy alternate CPU plans retain a second layout after first use. Steady-state
benchmarks include the extra setter work when requested, but do not include
initial plan allocation. ARM dispatch is unchanged pending measurements.
