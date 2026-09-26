# Using matchedfilter

This guide covers inputs, output bins, device selection and hierarchical
calibration. The examples execute during the documentation build. Run them
locally with `python -m matchedfilter.tutorial`.

## Install

```bash
pip install matchedfilter
```

The current release is alpha. Pin its version for reproducible work.
Wheels target CPython 3.9–3.14 on Linux x86-64 and macOS arm64. Source
installation requires NumPy and a C compiler.

## Inputs and normalization

`set_data()` and `set_templates()` accept frequency-domain arrays in natural
order, with shapes `(ndata, n)` and `(ntemplates, n)`. Use `complex64` spectra
from an unnormalized forward FFT, such as `numpy.fft.fft`. The filter computes
the unnormalized inverse transform of `data * conj(template)`.

Declare the dimensions when constructing the filter. Plans reuse storage;
first-use GPU dispatches and adaptive CPU layouts can still allocate.

[[example:A complete example]]

For unit-norm template spectra and independent noise with unit variance in
each real and imaginary component, the output magnitude has the normalization
used in these SNR examples. Other input normalizations change the scale of
`threshold`. Check the normalization of your data and template bank.

[[example:What comes back]]

## Output bins and thresholds

`run()` returns an array with shape `(ndata, ntemplates, nbins)`:

| Field | Type | Meaning |
|---|---|---|
| `index` | int64 | lag of the strongest sample in the bin; −1 if dismissed |
| `value` | complex64 | complex correlation at that lag; zero if dismissed |

`binsize` is the number of lags in each output bin. A full window with
`binsize=n` returns one peak per pair. A partial final bin is included.

[[example:One peak per window]]

`threshold` applies to the peak magnitude. Dismissed bins keep their place
in the output, so `peaks[d, t, j]` always refers to bin `j`.

[[example:Thresholding]]

`window=(start, end)` restricts the searched lags to `[start, end)`. Use it to
exclude the invalid wrap-around region when processing overlapping blocks.

[[example:Bounding the lags searched]]

## Output buffer lifetime

Results can reuse internal storage. Call `.copy()` to retain them after the
next filtering call. `raw=True` returns separate index and value arrays.

[[example:The output buffer is reused]]

## Filtering a time series

`run_series(series, starts, win_start, win_end)` accepts a time series and a
block layout. `starts` contains each block's starting sample; `win_start` and
`win_end` specify its valid output window. The caller supplies the overlap
layout. The library gathers and pads blocks, computes forward FFTs, and
filters them on the selected device.

Templates must be set first. A later `run()` requires another `set_data()`
call because series execution reuses the data slots. GPU execution is
synchronous. See the source documentation for
[GPU FFTs and shared storage](https://github.com/ahnitz/matchedfilter/blob/main/docs/gpu-forward-and-arrays.md)
for memory and interoperability details.

## Hierarchical filtering

`HierarchicalFilter` screens pairs using a coarse frequency band and refines
candidates with the full filter. Its output has the same format as `run()`;
screening can omit detections. `snr` and `fd` specify the signal strength and
requested false-dismissal budget used for calibration.

`set_reference(power)` supplies the expected output-power spectrum, one value
per frequency bin. Include the effect of the data's noise spectrum; a template's
power alone is generally insufficient for colored noise.

[[example:The hierarchical mode]]

Automatic configuration requires a covering measured calibration file. Missing
coverage raises an error. Alternatively, supply `band` when constructing the
filter and call `set_coarse_threshold(value)` before execution. Both explicit
parameters are required; no model or default threshold substitutes for them.
An explicit threshold carries no measured false-dismissal guarantee.

[[example:When it refuses]]

Validate the supplied calibration against your template population. A coarse
pass is most useful when it dismisses many pairs; dense survivors can make it
slower than flat filtering.

## Devices and supported sizes

```python
import matchedfilter as mf

print(mf.devices())
filt = mf.MatchedFilter(4096, ndata=16, ntemplates=64, device="gpu")
```

The default is CPU unless `MF_DEVICE` is set. `device="cpu"`, `"gpu"`,
`"gpu:1"` and `"auto"` are supported. Linux and Windows use Vulkan; macOS
uses Metal. GPU execution requires a compatible driver.

| Capability | CPU | GPU |
|---|---|---|
| Transform sizes | powers of two, 64–1,048,576 | powers of two, 64–65,536; device limits apply |
| Flat / hierarchical filtering | yes | yes |
| `run_series()` | yes | yes |
| Input spectra / output values | complex64 | complex64 |
| Flat and refinement arithmetic | float32 | float32 |
| Coarse screening | float32 | may use reduced precision |
| Output bins | arbitrary count | split internally above 2048 bins |
| Execution | one CPU thread | selected device |

GPU workgroup and shared-memory limits can reject individual sizes. Larger
bin counts may repeat GPU transforms because output is processed in chunks.
Unsupported requests raise an error; they do not switch devices.

CPU and GPU results can differ slightly because arithmetic ordering and coarse
screening differ. Near-equal maxima can select different lags. Transform support
is independent of hierarchical calibration coverage.

## Shared arrays and input ownership

`filter.empty_shared(shape)` allocates NumPy arrays backed by GPU-accessible
storage for GPU filters. Suitable contiguous `complex64` banks can bind without
an extra input copy. Call the setter again after changing a shared bank so
cached coarse templates are refreshed.

Host DLPack arrays are supported. Arbitrary CUDA or ROCm device allocations
are not imported through this interface. Finish producer writes before
filtering; cross-library GPU stream synchronization is not provided. Returned
peaks use ordinary NumPy storage.

The [CPU/GPU contract](https://github.com/ahnitz/matchedfilter/blob/main/docs/cpu-gpu-parity.md)
describes buffer ownership, cache lifetime and interoperability limits.

## Platform checks

Linux x86-64, Linux arm64 and macOS arm64 are exercised in CI. That coverage
does not establish performance or compatibility on every physical GPU.
Metal was also tested on an Apple M2; historical measurements are in the GPU
design notes. macOS x86-64 is not currently tested.

`matchedfilter.targets()` lists the available CPU targets,
`matchedfilter.backend()` reports the selected target, and `set_target()` or
`MF_ISA` selects a specific target for testing.
