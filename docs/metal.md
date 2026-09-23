# The Apple GPU back end

`matchedfilter.metal.MatchedFilter` runs the batched matched filter on the GPU
of an Apple Silicon Mac. It takes the same spectra and returns the same peaks
as `matchedfilter.MatchedFilter` -- same threshold, window, bin and row
conventions -- so the two can be swapped and compared pair for pair.

```python
from matchedfilter import metal

metal.available()                # True on an M-series Mac with this build
filt = metal.MatchedFilter(16384, ndata=16, ntemplates=256)
filt.set_data(data_spectra)
filt.set_templates(template_spectra)
peaks = filt.run(binsize=1024, threshold=5.5)
```

Lengths are the powers of two from 256 to 2^21. The CPU library, and the
hierarchical filter, are unchanged; the GPU back end is a separate extension
that shares nothing with the C kernels but the contract.

## Measured

Apple M2 (8 CPU cores, 10 GPU cores), macOS 26, 16 data segments against a
template bank sized for about 2^26 samples of work per call, bins of n/16.
Microseconds per pair, median; the GPU's peaks are checked against the CPU's
on every pair before anything is timed (`python -m matchedfilter.benchmark_metal`).

| n | pairs | CPU, 1 thread | CPU, 4 threads | GPU | MLX | GPU vs 1 thread | GPU vs 4 threads |
|---|---|---|---|---|---|---|---|
| 256 | 16384 | 0.494 | 0.221 | 0.083 | 1.606 | 5.9x | 2.6x |
| 1024 | 16384 | 1.877 | 0.527 | 0.213 | 2.229 | 8.8x | 2.5x |
| 4096 | 16384 | 8.307 | 2.275 | 0.643 | 5.917 | 12.9x | 3.5x |
| 16384 | 4096 | 40.36 | 11.53 | 5.168 | 25.69 | 7.8x | 2.2x |
| 65536 | 1024 | 176.6 | 51.15 | 22.05 | 112.3 | 8.0x | 2.3x |
| 262144 | 256 | 789.0 | 231.3 | 107.0 | 332.7 | 7.4x | 2.2x |
| 1048576 | 64 | 3657 | 1512 | 550.4 | 1179 | 6.6x | 2.7x |

"CPU, 1 thread" is the library as shipped (NEON_BF16 via Highway), which is
single-threaded by design. "4 threads" runs four plans over a quarter of the
bank each -- the parallelism the README leaves to the caller -- on the M2's
four performance cores. "MLX" is the direct MLX formulation described below.

**Small batches.** A GPU call has a fixed cost of about 200 us, the command
buffer's submission and completion. At n=4096 one pair takes 9.5 us on the
CPU and 203 us on the GPU; the GPU wins from about 25 pairs a call, and from
2 at n=65536. Give it the whole bank in one call.

## Why Metal and not MLX

MLX makes the obvious version a few lines:

```python
z = mx.fft.ifft(D[:, None, :] * mx.conj(T[None, :, :]), axis=-1) * n
a = mx.abs(z).reshape(nd, nt, nbins, binsize)
peaks = mx.argmax(a, -1), mx.max(a, -1)
```

That is correct, but every correlation is written to memory, read back to
take its magnitude, and read again for the maximum -- several full passes of
`nd * nt * n` complex values over a memory system that delivers about
100 GB/s. The whole point of this library is not to do that: most of the
output is discarded, so the fast version never forms it. A fused kernel does
the product, the inverse transform and the peak search in one pass over
on-chip memory and writes only the peaks. MLX's custom-kernel escape hatch
could host such a kernel, but then MLX contributes nothing but a dependency.

The table above measures the difference: the MLX formulation is 2-10x slower
than the fused kernels, and slower than the four-threaded CPU up to 2^18.

## Layout

    metal/kernels.metal    the Metal kernels (compiled at run time)
    metal/mf_metal.h       C interface, the mirror of ap_mf_*
    metal/mf_metal.m       host side: device, pipelines, buffers, dispatch
    metal/_metalmodule.c   the matchedfilter._metal Python extension
    python/matchedfilter/metal.py              the Python class
    python/matchedfilter/benchmark_metal.py    the benchmark above
    tools/metal_tune.py                        the kernel-shape sweeps
    tests/test_metal.py                        against numpy and the CPU

setup.py builds `matchedfilter._metal` on macOS only (`MF_NO_METAL=1` skips
it) and embeds `kernels.metal` as a string, which Metal compiles when a plan
is first built, per tile shape. Apple's command line tools are enough; the
Xcode `metal` compiler is not needed. `MF_METAL_SOURCE=path/to/kernels.metal`
compiles a different copy instead, for editing the kernels without
rebuilding.

## How the kernels work

**Up to n = 4096: one pass.** A threadgroup holds 4096 complex values -- one
pair at n=4096, four at 1024 -- eight per thread, in registers. The first
radix-8 stage loads `D[f] * conj(T[f])` straight from the two spectra, so the
product is never stored. The remaining Stockham stages exchange values through
threadgroup memory one real component at a time, which halves the buffer to
16 KiB. `|z|^2` then goes into the same buffer in natural order, and the bins
are searched there: bins of up to 128 lags by groups of lanes sized to the
bin, reduced with shuffles, and wider bins in 128-lag chunks per simdgroup,
then merged. The winning lag is marked in place, and only the thread holding
that value in registers writes the record. Nothing but the peaks leaves the
chip.

**Above 4096: four-step, n = A * B.** Spectra are stored as rows at ingest
(`x[f1 + A*f2]` at `f1*B + f2`), so pass 1 reads rows contiguously: product,
B-point transform, then the `w_n^(f1 k2)` twiddle from two small tables,
written to a scratch intermediate. Pass 2 transforms W2 adjacent columns of
length A. Its output for one k1 is a *run* of W2 consecutive lags, so a bin
can span threadgroups. Each run finishes the bins wholly inside it, and hands
the maxima of the pieces of its first and last bin to a small merge kernel.
Runs are scanned in lag order and ties go to the lower lag, which is what a
sequential scan reports.

The one intermediate round trip is what the four-step costs. Past 2^17 both
passes run at about DRAM bandwidth. A 262144-point pair moves about 32n bytes
(two spectra in, the intermediate out and back), about 8.4 MB, and at about
100 GB/s that is 84 us against the 107 measured. Scratch is bounded (64 MiB by
default, `MF_METAL_SCRATCH_MB`), so a large batch runs as several fills inside
one command buffer.

**Pair order.** Consecutive threadgroups share whichever of data and
templates is smaller, so that side stays in cache while the other streams
through once. It is worth 1.7x at n=1024 and little elsewhere. Output rows
are always `(d - d0) * nt + (t - t0)`, whatever the order.

## Accuracy

The GPU computes in float32 with IEEE-safe math (`MTLMathModeSafe`) and
twiddles from double-precision tables. Against a float64 numpy reference the
peak magnitudes agree to about 2e-7 relative at n=4096 and 3e-7 at 2^21, the
same order as the CPU kernels. Values differ from the CPU's in the last bits,
because the two evaluate the transform in different orders. So where two lags
in a bin are equal to within rounding, either back end may report either one,
and a peak within an ulp of the threshold can cross on one side only.
`tests/test_metal.py` allows exactly those two differences and nothing else.

## Tuning

The shape is chosen per length from sweeps on an M2
(`python tools/metal_tune.py onepass|fourstep`), each configuration checked
against numpy before it is timed. Values per thread and radix: 8 and 8,
fastest from 2048 up and within a few percent below. 16 and 16 is 25% slower
at 4096, because occupancy falls faster than the saved stage repays it. The
four-step split: A = 32 up to 2^17, then the smallest A that keeps B within
4096; W2 = 32 up to 2^16, then 16. Near the optimum the spread was under 10%.
Environment overrides, all for tuning: `MF_METAL_VPT`, `MF_METAL_RADX`,
`MF_METAL_TILE`, `MF_METAL_LOGA`, `MF_METAL_W2`, `MF_METAL_SCRATCH_MB`,
`MF_METAL_DINNER`.

Measured and not adopted: a one-pass kernel at n=8192 (all 32 KiB of
threadgroup memory, 512 threads) was 16% faster than the four-step there, with
one threadgroup per core. That was not enough to justify a third kernel shape.
Smaller scratch fills, to keep the intermediate in the system cache, were
slower at every size, because each fill serialises with the next.

## Not done

- The hierarchical filter still runs on the CPU only. Its first stage is a
  small band-limited transform, which is the regime where the GPU's per-call
  cost matters most. It would need batching across segments to benefit.
- Calls are synchronous. An asynchronous `run` that returns before the GPU
  finishes would hide the 200 us per call behind the caller's next ingest.
- Tuned on one machine. The defaults are an M2's; other M-series GPUs have
  more cores and different cache sizes, and should be swept with
  `tools/metal_tune.py` before their numbers are quoted.
