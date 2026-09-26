# CPU int16 and common-exponent SWAR measurements — 2026-09-26

No production dispatch or calibration changes are made by this study. The
measurement sources live in `tools/narrow_cpu/`; raw measurements are in
`docs/audits/cpu-int16-swar-2026-09-26/`.

## Conclusion

Int16 is not a general replacement for the current coarse kernels on this CPU.
Prequantized, block-scaled int16 is the most promising measured variant, but its
small AVX2 wins depend on size and batch shape. It regresses other shapes and all
measured AVX-512 shapes. The common-exponent AVX SWAR experiment works exactly on
the tested integer inputs, but offers no repeatable butterfly-only speedup and
loses heavily when nontrivial twiddles require field extraction and repacking.
These results do not rule out better generated codelets or a different packed
multiplication scheme.

## Scope and timing

Machine: AMD Ryzen AI MAX+ 395 (Zen 5), Linux, GCC version recorded in JSON.
Baseline: the native library built for commit `a5a63b6`, with its AVX-512 coarse
broadcast optimization; binary SHA256 recorded in JSON. The active checkout has
concurrent work, so measurements deliberately use a frozen native baseline.

The full-stage benchmark charges product formation, quantization when performed
per pair, FFT, decode and magnitude scan. It also measures re-ingesting the eight
data spectra on each call, with templates cached. Template ingestion, allocation,
fine refinement, hierarchical selection and Python overhead are excluded. The
baseline additionally returns peak indices and complex values; the prototype
returns magnitudes only, so these timings are optimistic for a drop-in replacement.
These are coarse-stage timings, not end-to-end hierarchy speedups.

Each candidate is paired with the baseline in alternating order. First sweep:
seven paired rounds, approximately 3 ms per timing sample, unpinned. AVX2 repeat:
eleven rounds, approximately 10 ms per sample, pinned to logical CPU 4. The source
now defaults to 10 ms. Raw paired samples are saved; frequency and background load
were not controlled. Small wins are provisional.

The AVX-only candidate uses 256-bit float instructions and 128-bit integer
instructions, compared with the library's SSE4 fallback: the library has no
AVX-only backend. This is instruction-set restriction on a modern Zen 5 host,
not a measurement on an older AVX-only processor. AVX2 and AVX-512 compare like
native targets. No inference about old Intel/AMD machines is warranted.

## Full-stage candidates

Ten modes cover radix-2 and fused radix-4 Q15, ordinary 16-bit arithmetic,
two-field SWAR using masked 32-bit arithmetic, widened `madd` complex products,
prequantized input banks, an FP32 version of the same radix-4 algorithm, and
block-scaled variants. Integer SWAR adds carry/borrow isolation masks; it does not
magically double the hardware's existing 16-bit lane count. It loses on every
measured ISA/shape. `madd` improves rounding in some cases but its interleaves and
widening do not produce an overall win here.

Fixed-scaled modes halve each butterfly. Block-scaled modes share a power-of-two
shift across a SIMD packet and FFT stage, choosing headroom from the maximum
complex L1 bound. They track that bound while storing stage outputs. Prequantized
modes separately normalize each input spectrum at ingestion; product formation is
then integer arithmetic. Their ingestion cost is included in the second timing.

Pinned AVX2 repeat, prequantized block-scaled mode. Values are baseline time divided
by candidate time; below 1 means a regression.

| Coarse size | Templates | Cached inputs | Including data ingestion |
|---:|---:|---:|---:|
| 256 | 32 | 0.990x | 0.973x |
| 256 | 128 | 1.019x | 1.012x |
| 512 | 32 | 1.043x | 1.028x |
| 512 | 128 | 1.056x | 1.052x |
| 1024 | 32 | 0.834x | 0.822x |
| 1024 | 128 | 1.022x | 1.017x |

The initial AVX2 sweep suggested 1.04–1.08x at 256/512; the repeat reduces that
claim. On the initial sweep, the same mode achieved 1.26–1.39x against SSE4 with
AVX-only restrictions, and 0.55–0.84x against AVX-512. The generic FP32 radix-4
control is itself substantially slower than production AVX2 codelets: faster than
that control is not sufficient evidence to replace the production implementation.

## True 256-bit AVX SWAR with a common exponent

`avx_swar.cpp` packs three biased signed integers into each FP64 mantissa:

    encoded = 2^52 + (x0 + 2^14) + 2^17*(x1 + 2^14)
                         + 2^34*(x2 + 2^14)

Four doubles per YMM therefore carry twelve logical values. The fixed FP64
exponent makes integer addition exact within the stated headroom. Bias and guard
fields prevent cross-field carries/borrows. We avoid directly adding two encoded
values: crossing 2^53 would discard a low bit. With enough common headroom, an
unscaled butterfly needs only offset-adjusted addition/subtraction. The scaled
variant clears each field's low bit before an exact half and exponent rebias,
matching signed floor division by two.

The twiddle experiment uses a fixed 45-degree Q15 rotation. It extracts each
field, multiplies in FP64, rounds the combined complex product once, and repacks.
This is a primitive experiment, not a full SWAR FFT. Both candidates start with
packed inputs; initial packing is excluded. Packed storage costs 8/3 bytes per
value versus two for native int16. The comparator uses 128-bit native integer
arithmetic and the same combined-product rounding, permitted on AVX-only hosts.

Pinned repeat, median of nine rounds of 20,000 passes over 1,536 complex
butterflies, nanoseconds per complex butterfly:

| Butterfly | Packed AVX SWAR | Native 128-bit integer | Speedup |
|---|---:|---:|---:|
| Unscaled, no twiddle | 0.074 | 0.074 | 0.994x |
| Unscaled, with twiddle | 1.460 | 0.157 | 0.108x |
| Halved, no twiddle | 0.103 | 0.108 | 1.043x |
| Halved, with twiddle | 1.590 | 0.189 | 0.119x |

The unpinned unscaled butterfly initially showed 1.052x; this did not repeat.
The halved butterfly's direction also changed between runs. Neither is a solid
win. Twiddle overhead is large in both runs. Disassembly confirms YMM FP64
arithmetic/logic and no YMM integer arithmetic in this AVX-only executable.
The AVX2 full-stage binary contains native YMM `vpmulhrsw` and `vpmaddwd`.

## Accuracy and calibration limits

All three ISA builds pass correctness exercises at 64, 128, 256, 512 and 1024:
noise, coherent inputs, alternating cancellation, zero data, reciprocal input
scales, partial template packets and whole/middle-half windows. The FP32 control
agrees with the native baseline within the harness tolerance. Integer SWAR
matches its native arithmetic counterpart exactly in these exercises and FDR
samples. The separate packed-AVX executable checks all four butterfly modes
against both a scalar oracle and native SIMD, including signed edge and odd/even
carry/borrow cases. These are bounded-input prototypes, not complete production
validation of nonfinite, extreme-dynamic-range or arbitrary external inputs.
A UBSan build was attempted but the host linker could not find its libubsan.

FDR experiment: 32,768 injected trials per coarse size on AVX2, four spectral
profiles, random fractional lags, retaining roughly 17,500 fine-detected trials.
The baseline's empirical 0.01 and 0.001 quantiles define unchanged thresholds.
Candidates are compared on exactly the same samples, with a paired-disagreement
budget of ceil(12.5% of baseline dismissals), matching the study's screening rule.
This uses empirical thresholds, not shipped calibration tables or every
calibration population.

* Prequantized fixed scaling fails at size 1024 / rate 0.001: four disagreements
  versus a budget of three, even though the total dismissed count is unchanged.
* Prequantized block scaling passes all six cells: 2, 0 and 1 disagreements at
  0.01 for sizes 256, 512 and 1024; zero at 0.001.
* A 2% downward-magnitude negative control fails every cell. A 0.4% control
  passes every cell, explicitly demonstrating limited sensitivity.
* Only about 18 reference dismissals occur per 0.001 cell. Passing is preliminary
  evidence, not certification that calibration tables remain valid. Broader
  populations and many more tail events are needed before production use.

On timing inputs, the block-scaled prequantized AVX2 mode's maximum relative peak
error is approximately 0.12–0.21%, not the earlier idealized 0.01% estimate.
Real product quantization, stage rounding and scaling must be included in any
precision claim.

## Next useful work

A generated Q15 codelet family with block scaling could remove generic stage
loop overhead, but it must beat the production FP32 baseline across shapes.
Band 512 on AVX2 is the clearest measured starting point. Keep dispatch unchanged
until the small wins reproduce and calibration/peak output contracts are covered.
For SWAR, further work needs a cheaper packed twiddle method or a codelet that
amortizes extraction across several operations; add/subtract-only packing is not
enough to justify a new full FFT implementation.

## Reproduce

Use a Python environment containing a built matchedfilter native module and NumPy.
Select the desired frozen baseline with PYTHONPATH. The harness builds only into
its temporary build directory and does not modify the library.

```sh
PYTHONPATH=/path/to/baseline python tools/narrow_cpu/run.py \
  --build-dir /tmp/mf-narrow-cpu --output /tmp/narrow.json --fdr
PYTHONPATH=/path/to/baseline taskset -c 4 python tools/narrow_cpu/run.py \
  --build-dir /tmp/mf-narrow-cpu --output /tmp/narrow-repeat.json \
  --isas avx2 --rounds 11
g++ -O3 -std=c++17 -mavx -mssse3 -msse4.1 -mno-avx2 -mno-fma \
  tools/narrow_cpu/avx_swar.cpp -o /tmp/avx-swar
taskset -c 4 /tmp/avx-swar
```

The C++ candidates are x86-only research tools. They are not package dependencies,
not selected automatically and do not add hardware requirements to standard CI.
