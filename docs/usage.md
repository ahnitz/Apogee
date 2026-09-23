# Using matchedfilter

Day-to-day reference: what goes in, what comes back, and how the hierarchical
mode is driven. Measured numbers are on the benchmark pages, not here -- a
performance table copied into prose goes stale the moment the code moves, and
this one did.

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

## Inputs and outputs

Inputs are **frequency domain**: the unnormalised forward transform of each
segment, in natural order. Produce them with whatever you already use (numpy,
MKL, FFTW); matchedfilter does not need to own that step.

The filter is built once and reused. Ingest conjugates the templates and
stores both sides in the layout the correlation loop walks, which costs a few
percent of a run and less as the batch grows.

`run` returns a structured array of shape `(ndata, ntemplates, nbins)` with
fields `index`, `value` and `magnitude`. Bins whose peak fell below the
threshold carry `index == -1`.

### Bounding the output

`binsize` sets how many lags share one reported peak: one record per bin, so
`binsize=n` gives a single peak per pair and `binsize=1024` gives `n/1024`.

`window=(start, end)` bounds which lags are searched at all. An overlap-save
caller should use it -- the wrap-around region of each block is invalid and
searching it is not free, particularly for the hierarchical mode, where every
extra lag is another chance for noise to force a reconstruction.

`run_series` takes a whole time series plus the block layout (`starts`,
`win_start`, `win_end`) and executes it in one call, which removes the
per-block round trip and lets the library group blocks internally.

## Choosing a transform length

Supported lengths are the powers of two from 1024 to 1048576. The hierarchical
mode additionally needs measured tuning coverage at that length; where it has
none it raises rather than guessing, and `tools/hmf_tune.py` generates more.

## Platforms

One kernel source is compiled once per SIMD target the compiler can generate,
and the target is chosen at run time from what the CPU reports. On x86-64
that is AVX3, AVX2 and SSE4; on arm64 it is NEON.

| platform | tested |
|---|---|
| Linux x86-64 | every push |
| Linux arm64 | every push |
| macOS arm64 | every push |
| macOS x86-64 | no |

macOS on Intel is untested rather than known-broken: hosted runners for it are
being retired, so nothing measures it. `matchedfilter.targets()` lists what a
build holds that the CPU can run, `matchedfilter.backend()` reports which one
was selected, and `set_target()` or `MF_ISA` forces one.
