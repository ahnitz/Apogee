# matchedfilter

Batched matched filtering with peak-only output, on CPU or GPU.

`matchedfilter` correlates data segments against a template bank and returns
the strongest sample in each output bin. It accepts `complex64` spectra or
time-series blocks through `run_series()`.

[Documentation](https://ahnitz.github.io/matchedfilter/) ·
[Usage guide](https://ahnitz.github.io/matchedfilter/using-it.html) ·
[Benchmarks](https://ahnitz.github.io/matchedfilter/benchmarks.html)

**Alpha software:** the API may change. Pin a version for reproducible work.

## Quick start

```bash
pip install matchedfilter
```

This example finds a template shifted by 37 samples:

```python
import numpy as np
import matchedfilter as mf

n = 1024
rng = np.random.default_rng(1)
template = rng.standard_normal(n)
data = np.roll(template, 37)

filt = mf.MatchedFilter(n, ndata=1, ntemplates=1)
filt.set_templates(np.fft.fft(template).astype(np.complex64)[None, :])
filt.set_data(np.fft.fft(data).astype(np.complex64)[None, :])
peaks = filt.run(binsize=n)
print(peaks["index"][0, 0, 0])  # 37
```

The result has shape `(ndata, ntemplates, nbins)`, with `index` and `value`
fields. `value` is complex; use `abs(value)` for its magnitude. Bins below
the detection threshold have `index == -1` and `value == 0`. Results may
reuse storage: copy any result you need to retain across calls.

See the [usage guide](https://ahnitz.github.io/matchedfilter/using-it.html)
for normalization, thresholds, search windows and time-series input.

## Supported capabilities

| | CPU | GPU |
|---|---|---|
| Transform sizes | powers of two, 64–1,048,576 | powers of two, 64–65,536; device limits apply |
| Flat and hierarchical filtering | yes | yes |
| Time-series input with `run_series()` | yes | yes |
| Input spectra and returned values | `complex64` | `complex64` |
| Execution | one CPU thread | Vulkan or Metal |

Flat filtering and refinement use single precision. GPU hierarchical
screening can use reduced-precision kernels. There is no float64 filtering API.

The default device is CPU unless `MF_DEVICE` is set. Select a GPU explicitly:

```python
print(mf.devices())
gpu_filter = mf.MatchedFilter(4096, device="gpu")
```

Linux and Windows use Vulkan; macOS uses Metal. A compatible driver is
required. Unsupported GPU requests raise an error. See the
[usage guide](https://ahnitz.github.io/matchedfilter/using-it.html)
for platform and device limits.

## Hierarchical filtering

`HierarchicalFilter` screens each pair using a low-frequency band, then runs
the full filter on candidates. It is useful when most pairs can be dismissed
and enough signal power lies in that band. Otherwise the screening stage can
add work without a useful saving.

Automatic selection uses your expected output-power spectrum and measured
calibration files. `snr` specifies the signal strength and `fd` the requested
false-dismissal budget for that calibration. Validate the calibration against
your template population before relying on it.

For example, with spectra and an output-power reference prepared as described
in the usage guide:

```python
hf = mf.HierarchicalFilter(4096, ndata=16, ntemplates=64, snr=5.5, fd=1e-2)
hf.set_reference(expected_output_power)
hf.set_templates(template_spectra)
hf.set_data(data_spectra)
peaks = hf.run(binsize=4096, threshold=5.5)
```

A request needs a covering calibration file, or an explicit coarse size and
coarse threshold. There is no calibration fallback. Transform support and
calibration coverage are separate.

## Performance

The implementation fuses the frequency-domain product and peak scan into the
transform stages, avoiding a separate full correlation output. Performance
depends on transform length, batch shape, device and the fraction of pairs
that require refinement.

![CPU and GPU matched-filter measurements at 4096 points](docs/assets/teaser.svg)

Measured on a Ryzen AI MAX+ 395 / Radeon 8060S, 2026-09-26: 16 data segments ×
1,024 templates, 4,096 points. The matchedfilter bars time warm `run()` calls,
including result assembly and GPU readback. FFTW and rocFFT time the inverse
transform only. The two panels use separate scales; compare their printed
values. These measurements are a workload example, not a speed guarantee.

The [flat](https://ahnitz.github.io/matchedfilter/benchmarks.html) and
[hierarchical](https://ahnitz.github.io/matchedfilter/hierarchical-benchmarks.html)
benchmark pages show results across available transform sizes.

## Run the benchmarks

```bash
python -m pip install pyfftw  # optional FFTW reference
python -m matchedfilter.benchmark --reps 7 --json bench.json
```

The default sweep covers all 15 CPU sizes, with GPU timings where supported.
Batch sizes shrink at large lengths to bound memory use. `--n` selects a subset.
Missing hierarchical calibration is reported explicitly.

Install `mkl-fft` and `mkl` for an optional MKL reference where supported.
NumPy provides the correctness reference. Without FFTW or MKL, library timings
and correctness checks still run. Reference timing covers the inverse FFT;
matchedfilter timing also includes the product and peak scan.

## Documentation

- [Usage guide](https://ahnitz.github.io/matchedfilter/using-it.html): inputs, normalization, devices and API behavior.
- [Examples](https://ahnitz.github.io/matchedfilter/demo.html): noise and injected signals.
- [Numerical accuracy](https://ahnitz.github.io/matchedfilter/precision.html): comparison with a float64 reference.
- [Design notes](https://ahnitz.github.io/matchedfilter/notes.html): implementation details and historical experiments.

## Status

This is an alpha release. Pin a version when reproducibility matters.
Hierarchical calibration covers a subset of input conditions; unsupported
requests require additional measurements or explicit coarse parameters.

Wheels target CPython 3.10–3.14 on Linux x86-64 and macOS arm64. Other platforms
build from source and need NumPy and a C compiler. CPU filtering uses one
thread; callers control parallelism across independent filters.

## Contributing

[Issues](https://github.com/ahnitz/matchedfilter/issues/new) and pull requests
are welcome. Useful contributions include device-specific benchmarks,
calibration measurements and testing on additional hardware.

```bash
git clone https://github.com/ahnitz/matchedfilter
cd matchedfilter
git submodule update --init third_party/highway
pip install -e .
pytest
```

GPU kernels are written in Slang. Rebuild the shipped SPIR-V and Metal sources
with `python tools/build_spirv.py --slangc /path/to/slangc`.

## License

MIT
