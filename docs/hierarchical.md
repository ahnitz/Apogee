# The hierarchical matched filter

The coarse stage correlates the first `band` spectral bins on a lag grid
spaced by `n / band`. It rejects a pair when its maximum is below the coarse
threshold. Surviving pairs run the full matched filter. CPU and GPU follow
this algorithm; arithmetic precision can move decisions near the gate.
Every reported survivor agrees with the flat filter within the backend's
floating-point accuracy. The hierarchy can omit triggers.

## Choosing the gate

Set the reference to the expected output power versus frequency (for the
usual whitened matched filter, proportional to `|H|² / S`). Its amplitude
cancels, but its **complete shape** matters. `gatemodel.gate_for` samples the
joint coarse and fine statistics, including correlated noise, spectral
truncation and lag-grid scalloping. It chooses the requested conditional
false-dismissal quantile at the constructor's `snr`.

`fd` is a model target for matching signals under Gaussian noise, not a
bound on every population or on every finite realization. Sampling error,
the local lag approximation and numerical precision remain. At narrow
bands the local approximation can be conservative because the real coarse
pass searches more lags. See [model validation and limitations](gate-model.md).

```python
hf = matchedfilter.HierarchicalFilter(n, ndata=16, ntemplates=32,
                                     snr=5.5, fd=1e-3)
hf.set_reference(power)
hf.set_templates(templates)
hf.set_data(data)
peaks = hf.run(binsize=n, threshold=5.5)
```

Configuration selection ranks candidates using measured **cost** files;
accuracy no longer comes from ACC/ACC2/THR files. `MF_COST` selects a local
cost file; GPU selection otherwise uses the most specific available device
cost table. Without usable costs, pin `band`. Without a resolvable model
budget, supply an explicitly validated gate as well:

```python
hf = matchedfilter.HierarchicalFilter(n, band=512)
hf.set_coarse_threshold(3.0)
```

An explicit band and gate need no reference or tuning file. With no
reference, coarse templates use their own in-band power fractions.
`set_coarse_threshold(None)` restores model gating and requires a reference.
`set_first_stage(snr)` changes the model's design SNR without changing the
final threshold or pinned configuration. `taps` is compatibility metadata;
there is no coarse interpolation or oversampling control.

## Reference groups and full-band scalloping

A single reference is not sufficient for an arbitrary heterogeneous bank.
Templates with the same in-band fraction can have different peak shapes,
and therefore different coarse-grid losses. Group compatible profiles or
validate an explicit gate for the entire bank.

Even retaining **all spectral power** does not make coarse and fine maxima
identical: the coarse grid still skips fine lags. A full-band gate may
therefore dismiss a trigger. Use `MatchedFilter` when an identical trigger
list is required; do not use `f=1` as a zero-dismissal guarantee.

## Cost and initialization

The model runs at plan preparation, not in the filtering loop. Conditional
samples are reused across gate queries and bounded by a 64 MiB LRU cache.
Tighter budgets need more samples (20,000 at .01, 200,000 at .001,
2,000,000 at .0001). Requests below the available resolution refuse rather
than falling back to an obsolete table. Kernel execution is unchanged.

Cost is approximately coarse work plus the fraction of pairs refined times
full-filter work. `refine_rate` reports this fraction over the plan's lifetime.
Cost files rank alternatives but are not runtime predictions: hardware,
batch shape, input population, window and budget affect the best choice.
Remeasure with `tools/hmf_tune.py --retune-cost --out mycost.txt` or use
`tools/audit_selection.py` to inspect the actual workload. Retuning uses
serial, interleaved measurements and the current model at fd=.001.
