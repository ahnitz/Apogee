# CPU and GPU timings at every supported size

AMD Ryzen AI MAX+ 395 (one CPU thread, AVX3), Radeon 8060S. The CPU supports
all 15 powers of two from 64 to 1048576; the GPU supports the first 11,
through 65536, subject to device limits.

Measured 2026-09-26 from a frozen package snapshot at bdfdad6. Values are
**milliseconds per batch**, median of nine alternating rounds of warm public
`run()` calls. Dispatch, synchronization, readback and output assembly are
included; initial upload, plan construction and forward FFTs are excluded.
The batch starts at **128 data × 512 templates**, then shrinks to keep input
spectra within 64 MiB. Compare devices within a row; batch times across rows
represent different amounts of work. Raw results also contain time per pair.

Gaussian noise, normalized inspiral-shaped templates, 60% search window,
one output bin and threshold 5.5. Hierarchical selection uses supplied files
at SNR=5.5, fd=0.001. Missing calibration is not a lack of transform support:
explicit coarse size and threshold can be supplied by callers. This table
does not guess either. Peak checks allow numerical ties only after checking
each reported lag against an independent transform.

| Points | Data × templates | CPU flat | GPU flat | CPU hierarchical | GPU hierarchical |
|---:|---:|---:|---:|---:|---:|
| 64 | 128 × 512 | 0.946 | 0.534 | not calibrated | not calibrated |
| 128 | 128 × 512 | 2.205 | 0.558 | not calibrated | not calibrated |
| 256 | 128 × 512 | 5.309 | 0.581 | not calibrated | not calibrated |
| 512 | 128 × 512 | 12.364 | 0.713 | not calibrated | not calibrated |
| 1024 | 128 × 512 | 28.324 | 1.310 | 6.758 | 0.341 |
| 2048 | 128 × 512 | 90.350 | 2.231 | 8.205 | 0.330 |
| 4096 | 128 × 512 | 194.688 | 6.523 | 24.656 | 1.919 |
| 8192 | 128 × 512 | 418.907 | 17.313 | 133.590 | 7.593 |
| 16384 | 64 × 256 | 196.782 | 8.682 | 61.057 | 6.408 |
| 32768 | 32 × 128 | 113.682 | 23.742 | 50.110 | not calibrated |
| 65536 | 16 × 64 | 63.317 | 72.294 | not calibrated | not calibrated |
| 131072 | 8 × 32 | 38.112 | unsupported | not calibrated | unsupported |
| 262144 | 4 × 16 | 20.681 | unsupported | not calibrated | unsupported |
| 524288 | 2 × 8 | 11.092 | unsupported | not calibrated | unsupported |
| 1048576 | 1 × 4 | 7.139 | unsupported | not calibrated | unsupported |

CPU and GPU may select different coarse bands and refine different fractions
of pairs. These are workload measurements, not signal-dismissal validation.
Shared-machine activity and GPU clock ramping affect timings; short alternating
rounds are not a guarantee of sustained peak throughput. Raw ranges, bands,
refinement rates and refusal reasons are recorded in
`docs/measurements/device-paths-all-sizes-2026-09-26.json`.

Reproduce the complete sweep:

```bash
python tools/bench_device_paths.py --rounds 9 --json timings.json
```

For FFTW/MKL reference timings across the same complete size list:

```bash
python -m matchedfilter.benchmark --json benchmarks.json
```

Use `--n` to deliberately select a subset. Explicit `--data` and `--templates`
keep a fixed batch instead of adapting memory use. Previous partial sweeps
remain in the historical measurement JSON files; they are superseded by this
complete coverage report.
