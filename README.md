# apogee

**Work in progress.** A testbed, not something to depend on yet. It has run on
one machine with one compiler, the API still moves, and the size list is short.

A single-threaded batched matched filter. Correlate D data segments against T
templates and get back, for each pair, the loudest sample in each bin of a search
window — index, complex value and magnitude. The full correlation output is never
formed.

It started as an FFT specialised for finding the loudest bins. The matched filter
is what that was always for, and it is now the interface; the transform is an
internal detail.

## The goal

Beat MKL and FFTW on one core at the thing a matched-filter search actually does,
using information they cannot assume: only the top point per bin matters, there
is a detection threshold, and only part of the output is searched.

The case it is built for is a white-noise time series where the peak is a ~5σ
fluctuation among a million bins. The output is not sparse, so sparse-FFT methods
do not apply — a coarse fold cannot find that peak.

## What it gives up

- **Only the loudest sample per bin is right.** Everything else is never computed
  to full accuracy and never written anywhere.
- **Accuracy is spent, not maximised.** The budget is 1e-5 relative to a
  double-precision reference. Worst measured across the test suite is 3.2e-07, so
  there is room left, but the design assumes the budget exists.
- **c2c float32, single-threaded, powers of two: 1024 and 2^12…2^20.** Not 2048 —
  the balanced split needs both factors at least one vector wide.
- **x86 with AVX2 minimum.** No scalar fallback.
- **Tuned for a busy machine**, where per-core bandwidth is scarce and the shared
  L3 is thrashed. On an idle box some choices would land differently.

## Interface assumptions

1. Inputs are **frequency domain** — the unnormalised forward transform of each
   segment, natural order, interleaved complex float32. Your pipeline has them
   that way; D+T forward transforms have no business inside a D×T loop.
2. Data and templates are the **same length**.
3. Correlation is **circular**. Zero-pad before ingest if you want linear.
4. The inverse is **unnormalised**, matching FFTW and MKL: a perfect match
   returns `n × energy`.
5. The window is in **lag space**, `[start, end)`.
6. Bins tile the window from `start`; the last may be ragged. Any size works,
   powers of two take the fast index path.
7. The threshold is on **magnitude**, one value per run.
8. **One peak per bin** — two candidates in one bin gives you the louder.
9. Ingest is amortised: spectra are stored in the layout the pair loop walks,
   which costs a rearrangement per segment and 2–4% of total.

## Numbers

One core of an AMD Ryzen AI MAX+ 395 (Zen 5), idle. D=T=16 (256 pairs), 60%
window, bin 1024, detection floor on.

The baselines are charged for their **inverse transforms only** — no product, no
peak scan, no forward transforms. apogee is charged for everything it does. That
is deliberately generous to them: it removes any argument about how well the
surrounding code was written, and sets the bar where it belongs, at "can a
peak-only matched filter beat a bare FFT?"

µs per pair, versus amd-fftw's bare inverse transform:

| N | AVX-512 | AVX2 |
|---|---|---|
| 2^10 | 0.65x | 0.37x |
| 2^12 | 0.67x | 0.45x |
| 2^14 | **1.31x** | 0.89x |
| 2^16 | **1.14x** | 0.83x |
| 2^18 | 0.99x | 0.75x |

So on AVX-512 the whole matched filter beats a bare inverse FFT at 2^14 and 2^16
and is close elsewhere. On AVX2 it is not there yet — that path costs 1.3–2.2x
its AVX-512 equivalent, while amd-fftw barely gains from AVX-512 at all (2^14:
14.1 µs AVX2 against 13.8 AVX-512). Closing AVX2 is the current work.

Against the *full* baseline route — product, inverse and scan, all vectorised —
apogee is 1.26–1.72x on AVX-512 and 0.85–1.26x on AVX2. Caveat: MKL takes its
generic path on this AMD part (`MKL_VERBOSE` says "Intel(R) Architecture
processors"), which is why amd-fftw is the number to watch.

## Using it

C:

```c
#include "apogee.h"

ap_mf_plan *mf = ap_mf_create(1u<<14, 16, 16);
for (int d = 0; d < 16; d++) ap_mf_set_data(mf, d, data_spectrum[d]);
for (int t = 0; t < 16; t++) ap_mf_set_template(mf, t, tmpl_spectrum[t]);

size_t nb = ap_mf_nbins(mf, 1024, start, end);
ap_peak *peaks = malloc(16*16*nb*sizeof *peaks);
int counts[16*16];
ap_mf_run(mf, 0,16, 0,16, 1024, threshold, peaks, counts, start, end);
/* pair (d,t) bin j -> peaks[(d*16 + t)*nb + j]; index -1 means no crossing */
ap_mf_destroy(mf);
```

Python:

```python
import numpy as np, apogee
mf = apogee.MatchedFilter(1 << 14, ndata=16, ntemplates=16)
mf.set_data(data_spectra)           # (16, 16384) complex64, already transformed
mf.set_templates(template_spectra)
peaks = mf.run(binsize=1024, threshold=t, window=(a, b))
peaks["index"], peaks["value"], peaks["magnitude"]   # (16, 16, nbins)
```

The whole D×T loop is one call into C — measured at 1.4% over the C path, so the
class costs nothing. `run(data=(d0,nd), templates=(t0,nt))` runs a sub-block and
gives exactly the matching slice of a full run.

There is no plan object to manage. The filter is the plan: build it once with
`(n, ndata, ntemplates)` and reuse it. Produce the spectra with whatever you
already use — apogee has no reason to own that step.

## How it works

The pair loop is 89% of the transforms before any optimisation, so every decision
is made about the pair loop.

Each pair is `IFFT(D_d · conj(H_t))` with the peak search fused in. The product
is formed inside the transform's first load, so it never reaches memory — 1 MiB
of L2 traffic per pair at 2^16. The backward transform's input conjugation folds
into that same multiply for free.

Spectra are stored **group-major**, `[n1 block][n2][lane]`. Stage A otherwise
reads a vector then jumps `N1` floats, a shape that sustains 7.6 GB/s here
against 43.9 sequential; owning the layout makes one group's whole pass
sequential. Ingest pays a transpose per segment so that all D×T pair transforms
read in order.

The peak search is a per-bin running maximum primed with the detection floor. A
bin never reports below the floor, so priming is exact, and it turns four
unconditional blends into a branch that is almost never taken.

Underneath: four-step decomposition with a balanced N₁×N₂ ≈ √N split, split
(real/imag separated) complex data so a complex multiply is four FMAs and no
shuffles, and generated unrolled Stockham codelets (`src/gen.py`) at radix 8×4 or
8×8 — two passes instead of radix-2's five. Those codelets run at 303 GF/s, 93%
of this machine's AVX-512 FMA peak.

`docs/machine-notes.md` is the lab notebook: measured instruction throughput,
pipe-overlap rules, the amd-fftw disassembly, and every idea that was tried and
dropped with the number that killed it. Non-temporal stores, huge pages, a
quantised intermediate, batch-interleaved layout, VNNI, bf16, split-radix,
prefetching at any distance — all measured, none kept.
`docs/matched-filter-plan.md` is the design and test plan for the current
interface.

## Build

apogee builds as a Python extension. That is the build:

```sh
pip install .
```

`pyproject.toml` is authoritative; `setup.py` exists only because the extension
needs per-source compiler flags (the AVX-512 sources, the AVX2 sources and the
dispatcher must be compiled differently so the module *loads* on a machine
without AVX-512 and still picks a working back end at runtime), which
declarative config cannot express.

The Makefile is for development — it builds the C tests and benchmarks, which
are much more thorough than the Python ones:

```sh
make test       # full suite on every back end
make quick      # 2 s correctness gate for use between edits
make codelets   # regenerate src/codelets.h from gen.py
```

Using it from C is not the priority, but it is allowed: the header ships in the
wheel and `apogee.include_dir()` points a compiler at it.

```sh
cc myprog.c -I"$(python -c 'import apogee; print(apogee.include_dir())')" ...
```

Benchmarks need MKL and an AOCL-FFTW build:

```sh
make bench/bench_mf MKLINC=/path/include MKLLIB=/path/lib AMDFFTW=/path/aocl
```

If you have neither, `python -m apogee.benchmark` needs only numpy. It runs the
same matched filter both ways, checks the answers agree, and reports per-pair
times — so you can see whether apogee works and is fast on *your* machine rather
than trusting numbers from one developer box. numpy is a floor, not a rival.

## Tests

`tests/test_mf.c` checks the matched filter against an independent
double-precision radix-2 FFT: every pair separately, a known-answer case
(template a circular shift of the data — the peak must be at exactly that lag
with magnitude `n × energy`), reuse invariance (a duplicated template must give
identical rows, which catches state leaking between pairs), blocking invariance
(any sub-block equals the matching slice of the whole), and shapes 1×1, 1×16,
16×1, 3×5, 16×16, 17×13.

`tests/test_binmax.c` covers the peak search itself against a brute-force scan —
481k checks over size × bin size × direction × window × threshold, including
empty bins, ragged final bins, bins that straddle vector blocks, and window
starts that are not bin-aligned.

`tests/test_units.c` covers the transpose, each codelet against a direct DFT, the
no-shift int16 codelets and their headroom bound, and analytic identities at
every size in both directions — impulse response, pure tone, Parseval, linearity,
and `backward(forward(x)) == n·x`.

`tests/test_python.py` checks the class API against numpy, including that the
Python layer adds no measurable cost.
