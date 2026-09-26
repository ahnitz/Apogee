# Retiring the accuracy table, 2026-09-26

`choose_threshold` now calls `gatemodel.gate_for` directly. The model uses
the complete reference power profile, the coarse grid and the correlated
coarse/fine Gaussian noise. ACC, ACC2, ACC2R and THR lookups are gone, along
with their files, margin placement, SNR envelopes and obsolete producers.
There is no accuracy-table fallback. Unresolvable budgets refuse; an
explicit band and coarse threshold still bypass model calculation.

`MF_ACCURACY` and `MF_THRESHOLD` now raise an explicit migration error
rather than silently overriding or being ignored by a model-driven gate.
`MF_COST` remains supported. The `tuning` argument to `choose_threshold`
remains accepted but cannot affect accuracy.

## The full-band blocker was a reference mismatch

At n=4096, band=2048, SNR=5 and fd=.001, the inspiral reference produces a
gate of **4.654114**. Modelled dismissal is **.00099356**; 100,000 independent
filter injections measured **.00101235**. This is not a quantile-placement
failure.

The old test ran sixteen different template profiles against that one
reference. The matched bank loses **0 of 48** fixed-seed noise triggers;
the heterogeneous bank loses **7 of 78**. Both retain all spectral power,
but the coarse step is still two fine samples: odd-lag peaks scallop.
Full spectral coverage does not imply identical coarse and fine maxima.

| Template power-law exponent | Own fd=.001 gate | Model dismissal at 4.654114 |
|---|---:|---:|
| −7/3 | 4.6541 | .000994 |
| −2 | 4.4227 | .00919 |
| −5/3 | 4.0665 | .04396 |
| −4/3 | 3.6491 | .12263 |

The replacement tests distinguish matching references, heterogeneous banks,
and deterministic loss between coarse-grid lags. They do not replace a
budget assertion with a permissive gate. The model's gate is unchanged by
this diagnosis. Reference groups or an explicitly validated common gate
are necessary for heterogeneous banks.

## Resolution and limitations

Samples have per-component noise variance one. They are conditioned on the
fine maximum crossing SNR before the coarse quantile is taken. fd=.01,
.001 and .0001 request 20,000, 200,000 and 2,000,000 draws respectively.
Roughly half survive conditioning, leaving approximately 100 tail events:
roughly 10% relative counting uncertainty, not an exact probability bound.
Budgets with fewer than eight conditional tail observations are refused.
Obviously unresolvable requests are rejected before allocating samples.

The covariance calculation and sampling run at plan preparation, not in the
filter loop. An LRU cache is capped at 64 entries **and 64 MiB**. Its key
includes normalized profile bytes, exact SNR, band, length, draw count and
seed. This fixes the previous omitted-seed and rounded-SNR cache aliases.
The recovered fraction is clamped against floating-point overshoot at one,
preventing a negative out-of-band variance at full coverage.

The model samples a local lag window. It is validated closely for the
recorded profiles and bands, not universally exact for every spectrum or
noise population. At band 128, n=4096, fd=.001, the inspiral-profile gate
2.5550 dismissed **0 of 100,000** trial injections. This is consistent with the local approximation omitting remote coarse
maxima; that mechanism has not been separately isolated here. This
conservatism can cost throughput. The tests assert budget compliance there,
not falsely claim two-sided 10% agreement. Non-Gaussian noise and template
profiles unlike the reference are outside the calibration assumptions.

An old strict xfail asserted that *measured* dismissal must fall when the
band widens, despite choosing a different gate for each band. That is not
an invariant: one gate can underspend its budget. Its replacement tests
that every band respects the requested budget, with sufficient counts.

## Independent 1e-4 measurement

At n=1024, band=256, SNR=5.5, the benchmark reference gave gate **4.1241884**.
With a seed independent of the model and 1.5 million requested injections:

- fine detections: **860,549**;
- dismissed: **82**;
- measured FDR: **9.5288e-5**;
- model FDR at that gate: **9.9967e-5**.

Reproduce with:

```sh
OPENBLAS_NUM_THREADS=1 PYTHONPATH=python python tools/audit_gate_model.py \
  --n 1024 --band 256 --snr 5.5 --fd .0001 --trials 1500000 --seed 417
```

The standard suite now runs a real `_bench_hier` point at fd=1e-4 and checks
quantile placement at all three budgets. The benchmark already swept 1e-4;
it can now produce actual timings rather than table-coverage refusals.
Its noise-only timing rows report **requested** FDR, not measured signal
loss. `audit_gate_model.py` reports empirical counts and Wilson intervals.

## Cost migration and performance

Cost measurements remain hardware-specific. The obsolete gate-scale axis
had inconsistent provenance across generations and cannot be interpreted
as an absolute gate for this model. Migration retains each cell's measured
baseline (the scale nearest one), with its numeric cost unchanged, and
removes the scale column. At that migration, the format was:

```
COST n band U K snr f beff relative_cost
```

Old ten-field cost files are rejected with a regeneration instruction.
The GPU retune documented below uses an explicit
`# format cost-fd-pairs-v1` header and places `fd` and `pairs` between
`snr` and `f`; this distinguishes its eleven-field rows from the obsolete
scale rows. CPU files keep nine fields.
Cost SNR coverage is resolved per configuration, so a sparsely measured SNR
cannot hide competing bands. Costs only rank bands; they never change a gate.
At this migration the cost table was an approximate ranking without a budget
or batch-shape axis. Retuning for a workload remains useful; this migration does not
claim globally optimal band selection.

Interleaved 8×32 timing on the same native build selected the same bands in
five checked cases. The comparison separates a changed gate from changed
selection. Full records and the harness are in
[audits/gate-model-2026-09-26](audits/gate-model-2026-09-26).

| n / SNR (fd=.001) | Old table gate (ms) | Model gate (ms) |
|---|---:|---:|
| 1024 / 5 | .0372 | .0393 |
| 4096 / 5 | .2055 | .2652 |
| 4096 / 6 | .1063 | .0990 |
| 16384 / 5 | 2.4205 | 2.8655 |
| 16384 / 6 | 1.6887 | 1.3624 |

These are not zero-cost changes: where the new gate admits more pairs, the
filter performs more refinement. No execution kernel changed in this
migration. Cold selection at fd=.001 cost .13–.14 seconds in these cases;
warm selection cost .09–.41 milliseconds. Tighter budgets increase cold
sampling cost. Comparing unsafe table gates solely on throughput would
hide the accuracy correction this task was requested to make.

## Teaser

The regenerated [teaser](assets/teaser.svg) uses the same matched-profile
bank for flat and hierarchical paths. The old heterogeneous bank did not
satisfy the reference contract. It now includes fd=.01, .001 and .0001 as
overlapping hierarchical bars: every boundary marks total throughput.
[Raw measurements](assets/teaser.json) include selected bands and refine rates.

Both filter devices time warm public `run()` calls; GPU readback and result
assembly are included. Baselines time full-batch inverse transforms only.
FFTW uses one thread, unnormalized execution and PATIENT planning capped at
15 seconds. rocFFT operates on initialized resident storage and amortizes
synchronization over eight executes. It is no longer labelled as saturating
memory bandwidth based on an unrelated historical measurement. Historical
Apple M2 constants are not mixed into a fresh model-generated figure.

At fd=1e-4, the 16×1024, n=4096 teaser measures **8.82 ms CPU** and
**.274 ms GPU**, versus flat **46.99 ms** and **1.347 ms**. This is a workload
example, not a general speed guarantee.

## Verification and shared-checkout isolation

Isolated validation: **844 passed, 6 skipped** on the Ryzen AI MAX+ 395 and
Radeon 8060S, with hardware GPU execution enabled. There are no remaining
xfails in that run. Linux CI without GPU hardware retains CPU/model checks;
Apple CI remains responsible for Metal execution.

A concurrent session was editing the class and GPU cache implementation.
Validation used a copy of committed code plus this task's changes, with the
same native extension (SHA-256
`e242d3696275d283950008e6331c485c6057dbe7b9dd960da3f9c6dee958c21d`).
The binary matches the concurrently committed CPU broadcast optimization.
Uncommitted class/cache changes were excluded from both the validation and
teaser timings. The shared checkout was not reset or overwritten.

The teaser was remeasured after competing jobs finished, using sustained
warmup and timing blocks: with the retuned GPU costs, fd=.01 reaches
**83.71 M/s**. See the
[throughput investigation](audits/gate-model-2026-09-26/gpu-throughput-investigation.md)
for historical timing differences and concurrent-workload evidence.

After the concurrent class/cache changes were committed, the combined
working tree passed **892 tests, 6 skipped** on CPU and Radeon 8060S.

## Radeon 8060S cost retune

The 8060S now ships a device-specific, FDR- and pair-count-aware cost table.
It ranks bands separately at three budgets and two measured batch sizes;
calibration still comes only from the reference gate model. See the
[retune audit](measurements/gpu-cost-retune-2026-09-26.md), including raw
measurements and independent holdout results. The prior gfx11 family table
remains for other hardware.
