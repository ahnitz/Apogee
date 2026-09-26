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
10.75× for band512/K4 in that run. That would be a selection performance
regression. More representative reference/batch coverage and validation of the
cost lookup are required before enabling those bands automatically. Explicit
band=64/128 remains supported and tested.

Lazy alternate CPU plans retain a second layout after first use. Steady-state
benchmarks include the extra setter work when requested, but do not include
initial plan allocation. ARM dispatch is unchanged pending measurements.
