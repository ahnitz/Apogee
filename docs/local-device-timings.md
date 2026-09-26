# Local CPU / GPU timings — 2026-09-26

AMD Ryzen AI MAX+ 395 (one CPU thread, AVX3) and Radeon 8060S. Each batch is
16 data rows × 64 templates = 1024 correlations. Values below are median
**milliseconds per batch** across nine alternating timing rounds after warmup.
Initial ingestion, GPU upload and pipeline creation are excluded; each timed
call includes dispatch and output readback. No forward FFT is included.

Inputs are Gaussian noise with normalized inspiral-shaped templates. The search
window covers 60% of the transform, with one output bin and threshold 5.5.
Hierarchical calibration uses the supplied files at SNR 5.5 and fd=0.001.
CPU/GPU flat peaks were compared, and hierarchical survivors checked against
the corresponding flat results, before timing.

| Points | CPU flat | GPU flat | CPU hierarchical | GPU hierarchical | CPU / GPU band |
|---:|---:|---:|---:|---:|:---|
| 1024 | 0.678 | 0.758 | 0.158 | 0.259 | 256 / 256 |
| 2048 | 2.396 | 0.598 | 0.175 | 0.236 | 256 / 256 |
| 4096 | 5.797 | 1.070 | 0.463 | 0.464 | 512 / 256 |
| 8192 | 12.911 | 7.047 | 4.473 | 3.715 | 2048 / 512 |
| 16384 | 24.560 | 14.262 | 6.466 | 10.870 | 2048 / 1024 |
| 32768 | 54.572 | 33.256 | — | — | — / — |
| 65536 | 146.014 | 199.955 | — | — | — / — |

“—” means calibration/configuration coverage is missing, not an estimated time.
CPU and GPU choose different calibrated bands at some sizes, so hierarchical
comparisons include the selection policy as well as execution speed. These
noise timings are not signal-dismissal measurements or comparisons with the
larger batch in the README teaser.

The frozen working-tree snapshot includes ongoing 32768/65536-point GPU work
not yet committed at measurement time. Shared-machine timing is noisy:
65536-point GPU rounds ranged from 148.8 to 207.5 ms. Treat the medians as local
observations, not a performance guarantee. Raw ranges and refinement rates are
in `docs/measurements/device-paths-2026-09-26.json`.

```bash
python tools/bench_device_paths.py --data 16 --templates 64 --rounds 9 --json timings.json
```
