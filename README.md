# matchedfilter

A fast single-threaded matched filter for x86. You give it a batch of data
segments and a batch of templates; it correlates every pair and hands back only
the peaks.

Not returning the full correlation is the point. Most searches threshold the
output and throw the rest away, and once you say so up front the filter can
skip work that could not have produced a peak anyway.

> **Status: work in progress.** The API still moves, and there is a known
> calibration weakness in the hierarchical filter. See
> [Caveats](#caveats).

```python
from matchedfilter import MatchedFilter

mf = MatchedFilter(16384, ndata=16, ntemplates=64)
mf.set_data(data_spectra)          # (16, 16384) complex64, already FFT'd
mf.set_templates(template_spectra) # (64, 16384) complex64

peaks = mf.run(binsize=1024, threshold=5.5)
peaks["index"], peaks["value"], peaks["magnitude"]
```

## Install

```bash
pip install git+https://github.com/ahnitz/matchedfilter
```

Needs numpy and a C compiler. x86-64 with AVX2; AVX-512 is used when present.

## How it works

Inputs are **frequency domain**: the unnormalised forward transform of each
segment, in natural order. Produce them with whatever you already use (numpy,
MKL, FFTW); matchedfilter does not need to own that step.

The filter is built once and reused. Ingest conjugates the templates and
stores both sides in the layout the correlation loop walks, which costs a few
percent of a run and less as the batch grows.

`run` returns a structured array of shape `(ndata, ntemplates, nbins)` with
fields `index`, `value` and `magnitude`. Bins whose peak fell below the
threshold carry `index == -1`.

Supported lengths are 1024 and the powers of two from 4096 to 1048576.

### Performance

Per (data, template) pair, 8x32 batch, one core of a Zen 5 desktop:

| n | matchedfilter | numpy | |
|---:|---:|---:|---:|
| 1024 | 0.61 µs | 18.98 µs | 31x |
| 4096 | 2.08 µs | 37.81 µs | 18x |
| 16384 | 9.98 µs | 127.04 µs | 13x |
| 65536 | 48.87 µs | 568.56 µs | 12x |

numpy is a floor, not a rival. It is there so the comparison runs anywhere.
Against MKL or FFTW the margin is much smaller, and part of what is left comes
from computing peaks instead of a full correlation. Measure on your own box:

```bash
python -m matchedfilter.benchmark
```

## Hierarchical filtering

`HierarchicalFilter` adds a cheap pre-pass: correlate against a low-frequency
slice of the template, and only run the full-length filter where that slice
leaves a peak plausible.

**This helps only under an assumption about your templates**: that enough of
the matched-filter output power sits in the low band that a narrow slice gives
a usable bound on the full result. For chirp-like templates whose power is
concentrated at low frequency that tends to hold. For templates whose power is
spread flat across the band, or concentrated high, the slice bounds nothing
useful, and the pre-pass is pure added cost. It is worth checking against your
own templates before relying on it.

```python
from matchedfilter import HierarchicalFilter

hf = HierarchicalFilter(16384, ndata=16, ntemplates=64,
                        snr=6.0,      # threshold you intend to use
                        fd=1e-3,      # false-dismissal budget
                        band=2048)    # width of the cheap slice

hf.set_reference(expected_output_power)      # power spectrum of the OUTPUT
hf.set_templates(template_spectra)
hf.set_data(data_spectra)
peaks = hf.run(binsize=16384, threshold=6.0)
```

`set_reference` takes the power spectrum of the filter **output**, not of the
template. Those differ whenever the data is coloured, and passing the template's
spectrum will mis-set the gate.

The gate is one-sided by construction: peaks it reports are bit-identical to
the flat filter's. It can only omit, never invent. `fd` is the budget for how
often it is allowed to omit one.

On pure noise at n=4096 the gate runs about **7x faster** than the flat filter.
The saving scales with how little survives, so it grows with your threshold and
falls toward 1x on data where most pairs trigger.

## Caveats

- **The false-dismissal budget is not currently met at low thresholds.**
  `fd` is honoured well at snr 6 and above. At snr 5.0 to 5.5 with a coarse
  band the gate omits more than it should: 1.4% against a 0.1% budget in a
  418-template search. The cause is that the gate's recovery factors are
  measured from a mean spectrum, which is not a bound on any individual
  realisation. Tracked by an `xfail` test in `tests/test_api.py` and written up
  in [docs/hierarchical.md](docs/hierarchical.md).
- Single-threaded by design. Parallelism is the caller's to arrange.
- x86-64 only.

## Development

```bash
pip install -e .[test]
pytest              # includes a C test that builds itself from source
python -m matchedfilter.benchmark
```

[docs/](docs/) holds the design notes: how the hierarchical gate is
calibrated, and measurements of the approaches that were tried and rejected.

## License

MIT
