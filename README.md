# peakfft

Single-threaded AVX-512 complex-to-complex float32 FFT, specialised for finding the
**loudest bins** — the largest `|X[k]| = sqrt(re²+im²)`.

Sizes 2^10 and 2^20. Two entry points:

```c
pf_plan *p = pf_create(1u<<20);
pf_fft (p, in, out);                     // exact full transform
pf_topk(p, in, 8, idx, re, im);          // only the 8 largest |X|, descending
pf_destroy(p);
```

## Results

Single core, complex float32, forward. Measured on an AMD Ryzen AI MAX+ 395 (Zen 5)
under heavy concurrent load — the deployment condition this is tuned for, where DRAM
bandwidth per core is ~2.7 GB/s and the shared L3 gives no benefit over DRAM.
Interleaved A/B timing, minimum and median over many batched blocks.

| N | MKL 2026 | FFTW 3.3.10 (PATIENT) | `pf_fft` (exact) | `pf_topk` (K=8) |
|---|---|---|---|---|
| 2^10 | 0.89 µs | 0.92 µs | **0.48 µs — 1.9x** | 0.63 µs — 1.4x |
| 2^20 | 17.5 ms | 17.2 ms | 9.7 ms — 1.8x | **7.3 ms — 2.3x** |

Medians track the minima: 2.0x at 2^10 and 2.4x at 2^20.

Accuracy versus MKL, over 145 independent checks: **max 3.2e-7 relative**, and the
reported top-K bin *indices* agree with MKL exactly in every trial.

At 2^10 the top-K path is *not* the fast one — the full output write costs only 0.04 µs,
so there is nothing to save, while scanning 1024 magnitudes costs more than that. Use
`pf_fft` at 2^10. At 2^20 the output is 8 MiB and not writing it is worth ~3 ms, which is
where `pf_topk` pulls ahead.

## How it works

At 2^20 the transform is entirely DRAM-bandwidth-bound, so the design minimises bytes
moved rather than flops. A traffic model (`time ≈ bytes ÷ 2.7 GB/s`) predicted every
measurement here to within a few percent and drove every optimisation.

- **Four-step decomposition** — 32×32 at 2^10, 1024×1024 at 2^20.
- **Split (SoA) complex layout** — a complex multiply is 4 FMAs with no shuffles.
- **Generated unrolled Stockham codelets** (`src/gen.py`) — radix-8×4, so a 32-point
  transform is 2 passes rather than radix-2's 5. Twiddles are compile-time constants and
  trivial ones (±1, ±i) cost no multiplies. Worth 1.65x on its own at 2^10.
- **Stage 1 is SIMD-across-16-transforms**, which makes the strided column reads 128-byte
  full-cache-line granules *and* makes the SIMD lane index identical to the intermediate's
  column index — so stage 1 needs no transposes at all.
- **Padded element stride (33, not 32)** — stride-2048 B access mapped onto ~2 L1 sets and
  thrashed; padding made that sub-stage 13x faster.
- **Non-temporal stores** for the intermediate, avoiding read-for-ownership: 4x on that write.
- **Two-level twiddle factorisation** `W_N[n1·k2] = W_N[16g·k2]·W_N[l·k2]`, keeping tables
  at 128 KiB instead of 8 MiB.

What the top-K assumption buys, concretely:

- **The 8 MiB output is never materialised.** Magnitudes are reduced in-register against a
  running K-th-largest threshold.
- **The intermediate is stored at reduced precision.** It is quantised to 24-bit
  block-floating-point split across a 16-bit screening plane and an 8-bit residual plane.
  Screening reads only the 16-bit plane; the residual is touched only for the few columns
  that actually contain a winner, which are then recomputed at full precision. This halves
  the round-trip traffic while keeping the *reported* values accurate to ~3e-7.

Note this is deliberately **not** a sparse-FFT method. Sparse/aliasing approaches sample the
spectrum coarsely and find isolated tones; they cannot locate a ~5σ fluctuation among 2^20
white-noise bins, which is the target case here.

## Build

```sh
make            # library + tests
make test       # unit tests + top-K validation
make test-mkl MKLINC=/path/include MKLLIB=/path/lib   # cross-check against MKL
make bench    MKLINC=/path/include MKLLIB=/path/lib   # vs MKL and FFTW
```

Requires AVX-512 (F, DQ, BW, VL). `make codelets` regenerates `src/codelets.h`.

## Tests

- `tests/test_units.c` — transpose, each codelet vs a direct DFT, codelet stride
  equivalence, the 24-bit quantiser, the top-K heap, the 1024-point transform against a
  double-precision O(N²) DFT, and analytic identities at both sizes (impulse response, pure
  tone, Parseval, linearity). No external FFT library needed.
- `tests/test_topk.c` — `pf_topk` against a brute-force ranking of `pf_fft`, over white
  noise, noise+tone, noise+5 tones, and a deliberate near-tie, for K = 1, 8 and 64.
- `tests/test_vs_mkl.c` — the independent check: bounds the error the reduced-precision
  intermediate actually introduces, which the self-consistency tests cannot.
