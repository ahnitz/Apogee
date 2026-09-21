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
import matchedfilter as mf

filt = mf.MatchedFilter(16384, ndata=16, ntemplates=64)
filt.set_data(data_spectra)          # (16, 16384) complex64, already FFT'd
filt.set_templates(template_spectra) # (64, 16384) complex64

peaks = filt.run(binsize=1024, threshold=5.5)
peaks["index"], peaks["value"], peaks["magnitude"]
```

`import matchedfilter as mf` is the convention used throughout these docs.

## Install

```bash
pip install matchedfilter
```

Every release so far is an alpha, and pip installs a pre-release when that is
all a project has. Once a stable version exists, getting an alpha will need
`pip install --pre matchedfilter`.

Wheels are built for CPython 3.9 to 3.13 on Linux x86-64 (manylinux and
musllinux) and macOS arm64. Anywhere else pip falls back to the source
distribution, which needs numpy and a C compiler -- including Linux arm64,
where it builds and passes but no wheel is published yet.

### Platforms

x86-64 has hand-written AVX-512 and AVX2 kernels, chosen at run time from the
CPU. Everywhere else builds a portable back end from the same source, using
compiler vector extensions, which currently costs roughly 10% against the AVX2
kernels on the same machine.

| platform | back end | tested |
|---|---|---|
| Linux x86-64 | AVX-512 / AVX2 | every push |
| Linux arm64 | portable (NEON) | every push |
| macOS arm64 | portable (NEON) | every push |
| macOS x86-64 | AVX-512 / AVX2 | no |

macOS on Intel is untested rather than known-broken: hosted runners for it are
being retired, so nothing measures it. `matchedfilter.backend()` reports which
kernel was selected, and `MF_ISA` forces one.

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
hf = mf.HierarchicalFilter(16384, ndata=16, ntemplates=64,
                           snr=6.0,   # threshold you intend to use
                           fd=1e-3,   # false-dismissal budget
                           band=2048) # width of the cheap slice

hf.set_reference(expected_output_power)      # real frequency series, the OUTPUT
hf.set_templates(template_spectra)
hf.set_data(data_spectra)
peaks = hf.run(binsize=16384, threshold=6.0)
```

`set_reference` takes a real frequency series of length `n` holding the expected
power of the filter **output** in each bin. Only its shape is used; the overall
normalisation is divided out.

This is the output, not the template. The two differ whenever the data is
coloured, and passing the template's own power will mis-set the gate: a
broadband template reconstructing a narrowband signal is the case where it goes
wrong by the largest factor.

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
  measured from a mean frequency series, which is not a bound on any
  individual realisation. Tracked by an `xfail` test in `tests/test_api.py` and written up
  in [docs/hierarchical.md](docs/hierarchical.md).
- Single-threaded by design. Parallelism is the caller's to arrange.
- Off x86-64 the portable back end is the only one, and it currently costs
  about 10% against the AVX2 kernels measured on the same machine. See
  [docs/portable.md](docs/portable.md).

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
