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
| 1024 | 0.620 | 0.303 | 0.156 | 0.325 | 256 / 256 |
| 2048 | 2.589 | 0.483 | 0.173 | 0.266 | 256 / 256 |
| 4096 | 5.521 | 0.704 | 0.431 | 0.654 | 512 / 256 |
| 8192 | 12.854 | 1.492 | 4.557 | 0.859 | 2048 / 512 |
| 16384 | 23.510 | 2.785 | 7.282 | 2.267 | 2048 / 1024 |

CPU and GPU choose different calibrated bands at some sizes, so hierarchical
comparisons include the selection policy as well as execution speed. These
noise timings are not signal-dismissal measurements or comparisons with the
larger batch in the README teaser.

These measurements supersede the original table after fixing the shared
flat/refinement shader regression. They use the committed-source kernel set
(through 16384 points), with the fix applied; the concurrent wider-kernel work
is excluded. The previous 32768/65536 measurements are not corrected results
and are retained only in the original raw JSON. Shared-machine timings vary.
See [the regression investigation](gpu-performance-regression.md).
Raw corrected ranges and refinement rates are in
`docs/measurements/device-paths-fixed-2026-09-26.json`.

```bash
python tools/bench_device_paths.py --n 1024 2048 4096 8192 16384 --data 16 --templates 64 --rounds 9 --json timings.json
```
