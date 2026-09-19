# peakfft

> **Status: work in progress / experimental.** This is a testbed, not a production
> library. The API will change, the size coverage is narrow, and it has only ever
> been run on one machine and one compiler. Treat the numbers below as "measured
> here, once" rather than as a general claim.

A single-threaded AVX-512 complex-to-complex float32 **forward** FFT, specialised for
finding the **loudest bins** — the largest `|X[k]| = sqrt(re² + im²)`.

## The aim

Beat Intel MKL on a single core for complex float32 FFTs, given one extra piece of
information MKL is not allowed to assume: **we only care about the X loudest output
points**, not the whole spectrum. The motivating case is a matched-filter search, where
the output is essentially a white-noise time series and the question is only "what is the
loudest sample, and how loud". The peak is a ~5σ fluctuation among millions of bins — not
a sparse spectrum.

## What it is willing to give up to get there

This is the interesting part; each of these is a deliberate trade, not an oversight.

- **Only the top-K values are correct.** `pf_topk` never produces the other N−K bins at
  full accuracy, and never even writes them to memory. (`pf_fft` is still available and
  produces the complete exact transform.)
- **Accuracy is spent down to a budget, not maximised.** The target is 1e-5 relative
  versus MKL. Internally the bulk of the large-N arithmetic runs on a 24-bit
  block-floating-point intermediate rather than fp32. Measured worst case over 305
  independent checks is 3.6e-7, so there is ~27x of headroom left — but the design
  *assumes* the budget exists and would not survive a demand for bit-exactness.
- **Forward, complex-to-complex, float32, single-threaded only.** No inverse, no real
  transforms, no double, no multi-core. Running over multiple cores is not an algorithmic
  improvement, so it is deliberately out of scope.
- **Power-of-two sizes 2^10 and 2^12 … 2^20 only.** Nothing else; `pf_create` returns NULL.
- **AVX-512 required** (F, DQ, BW, VL). There is no scalar or AVX2 fallback.
- **Tuned for a *loaded* machine.** The design target is a box where all cores are busy,
  so per-core DRAM bandwidth is scarce (~2.7 GB/s here) and the shared L3 is thrashed to
  uselessness. On an idle machine the balance between the tuning choices would differ.

## Results

Single core, forward c2c float32, on an AMD Ryzen AI MAX+ 395 (Zen 5) under heavy
concurrent load. Interleaved A/B/C/D timing, batched calls, minimum over 4 runs.

![benchmark](bench.png)

| N | MKL 2026 | FFTW 3.3.10 PATIENT | `pf_fft` (exact) | `pf_topk` (K=8) |
|---|---|---|---|---|
| 2^10 | 0.91 µs | 0.89 µs | **0.47 µs — 1.93x** | 0.63 µs — 1.44x |
| 2^12 | 4.95 µs | 5.08 µs | 4.10 µs — 1.21x | 4.18 µs — 1.18x |
| 2^13 | 12.1 µs | 11.9 µs | 8.44 µs — 1.43x | 8.43 µs — 1.43x |
| 2^14 | 35.5 µs | 37.6 µs | 19.9 µs — 1.78x | **17.8 µs — 1.99x** |
| 2^15 | 92.1 µs | 104 µs | 57.3 µs — 1.61x | **47.5 µs — 1.94x** |
| 2^16 | 215 µs | 320 µs | 222 µs — 0.97x | **95.5 µs — 2.25x** |
| 2^17 | 833 µs | 925 µs | 770 µs — 1.08x | **516 µs — 1.61x** |
| 2^18 | 4.36 ms | 4.39 ms | 2.13 ms — 2.04x | **1.59 ms — 2.74x** |
| 2^19 | 6.86 ms | 6.92 ms | 4.69 ms — 1.46x | **3.59 ms — 1.91x** |
| 2^20 | 15.1 ms | 13.7 ms | 9.60 ms — 1.57x | **7.31 ms — 2.06x** |

`pf_topk` beats MKL at every size (1.18x – 2.74x). `pf_fft` is at parity around
2^16–2^17 and ahead elsewhere.

Accuracy versus MKL across 305 independent checks: **max 3.6e-7 relative**, and the
reported top-K bin *indices* match MKL exactly in every trial.

Two caveats on the numbers. MKL takes its generic code path on this AMD part
(`MKL_VERBOSE` reports "Intel(R) Architecture processors"), so some of the margin is
dispatch rather than algorithm — which is why FFTW is reported alongside. And at 2^10
the top-K path is *not* the fast one: the full output write costs only 0.04 µs, so there
is nothing to save, while scanning 1024 magnitudes costs more than that. Use `pf_fft`
below ~2^13.

## Usage

```c
#include "peakfft.h"
pf_plan *p = pf_create(1u << 20);
pf_fft (p, in, out);                    // exact full transform
int n = pf_topk(p, in, 8, idx, re, im); // 8 loudest bins, descending
pf_destroy(p);
```

## How it works

At large N the transform is entirely DRAM-bandwidth-bound, so the design minimises bytes
moved rather than flops. A traffic model (`time ≈ bytes ÷ 2.7 GB/s`) predicted every
measurement to within a few percent and drove each optimisation.

- **Four-step decomposition.** N = 1024×1024 at 2^20 (stage 2 is the L1-resident 1024-point
  kernel); a balanced N₁×N₂ ≈ √N split for 2^12–2^16, where everything is L2-resident and
  nothing needs quantising.
- **Split (SoA) complex layout** — a complex multiply is 4 FMAs with no shuffles.
- **Generated unrolled Stockham codelets** (`src/gen.py`) — radix-8×4, so a 32-point
  transform is 2 passes rather than radix-2's 5. Twiddles are compile-time constants and
  trivial ones (±1, ±i) cost no multiplies. Worth 1.65x on its own at 2^10.
- **Stages are SIMD-across-16-transforms**, which makes strided column reads 128-byte
  full-cache-line granules *and* makes the SIMD lane index equal to the intermediate's
  column index — so no in-register transposes are needed inside a stage.
- **Padded element stride (33, not 32)** — stride-2048 B access mapped onto ~2 L1 sets and
  thrashed; padding made that sub-stage **13x** faster.
- **Non-temporal stores** for the intermediate, avoiding read-for-ownership: **4x** on that
  write.
- **Two-level twiddle factorisation** `W_N[n₁·k₂] = W_N[16g·k₂]·W_N[l·k₂]`, keeping tables
  at 128 KiB instead of 8 MiB.

What the top-K assumption buys, concretely:

- **The output is never materialised.** At 2^20 that is 8 MiB not written, worth ~3 ms.
  Magnitudes are reduced in-register against a running K-th-largest threshold, primed from
  a cheap per-lane-maximum pass so the scan almost never branches.
- **The intermediate is stored at reduced precision** (2^17 and above): 24-bit
  block-floating-point, split across a 16-bit screening plane and an 8-bit residual plane.
  Screening reads only the 16-bit plane; the residual is touched only for the few columns
  that actually contain a winner, which are then recomputed at full precision.

This is deliberately **not** a sparse-FFT method. Sparse/aliasing approaches sample the
spectrum coarsely and find isolated tones; they cannot locate a ~5σ fluctuation among 2^20
white-noise bins, which is the target case.

## Build

```sh
make            # library + tests
make test       # unit tests + top-K validation
make test-mkl MKLINC=/path/include MKLLIB=/path/lib   # cross-check against MKL
make bench    MKLINC=/path/include MKLLIB=/path/lib   # vs MKL and FFTW
```

`make codelets` regenerates `src/codelets.h`. CI builds with explicit AVX-512 flags,
runs the tests when the runner supports them, and fails if `codelets.h` drifts from
`gen.py`.

## Tests

- `tests/test_units.c` — transpose, each codelet vs a direct DFT, codelet stride
  equivalence, the 24-bit quantiser, the top-K heap, the 1024-point transform against a
  double-precision O(N²) DFT, and analytic identities at *every* supported size (impulse
  response, pure tone, Parseval, linearity). Needs no external FFT library.
- `tests/test_topk.c` — `pf_topk` against a brute-force ranking of `pf_fft`, over white
  noise, noise+tone, noise+5 tones and a deliberate near-tie, for K = 1, 8, 64.
- `tests/test_vs_mkl.c` — the independent check. This is the one that bounds the error the
  reduced-precision intermediate actually introduces; the other two are self-consistent by
  construction and cannot catch it.
