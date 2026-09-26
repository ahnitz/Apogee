# GPU timing regression and benchmark correction

The September 26 size sweep exposed two separate problems.

* The teaser timed CPU `run()` but replayed private GPU command buffers. GPU
  readback and result assembly were omitted. Both device bars now time the
  public `run()` API after warmup; a regression test checks that contract.
* Coarse-template tiling added a wrapper and register-array argument around
  the shared full-precision filter. Disabling the unused loads did not restore
  performance. Making the full-precision implementation the direct `filterPair`
  body restores the fast path, while keeping the coarse tiling implementation.
  Both flat and compacted refinement use this corrected body.

An interleaved historical-binary comparison at 4096 points and 16 × 1024
correlations located the slowdown at the coarse-template tiling change
(`a7ea551`). The committed pre-fix kernel took 10.06 ms versus 5.06 ms for
this fix and 4.71 ms for the older `b611cf2` kernel in the same comparison.
Absolute times varied across runs on this shared machine; the approximately
2× difference persisted in interleaved comparisons. This is a measured kernel
regression, not evidence that Python or `run_series()` caused those timings.

The rebuilt committed-source kernels passed 124 GPU tests covering reference
accuracy, the public API, caching and hierarchical behavior. Metal source was
regenerated but Metal execution was not tested on this Linux machine.

The teaser and size sweep remain different workloads: 16 × 1024 versus
16 × 64 pairs, full versus 60% windows, differing template populations, and
fd=0.01 versus fd=0.001. Smaller batches amortize GPU dispatch overhead less
well. A GPU win is not guaranteed at every size or calibration setting.

## Original large workload, rerun after the fix

The regenerated teaser (4096 points, 16 × 1024 pairs, full window, fd=0.01)
measured these public-API times:

| Path | CPU ms | GPU ms | GPU speedup |
|---|---:|---:|---:|
| Flat | 48.16 | 1.31 | 36.8× |
| Hierarchical | 3.17 | 0.23 | approximately 14× |

The old chart was approximately 40× flat and 34× hierarchical, not a universal
50× claim. Current hierarchical calibration and CPU performance also differ;
no threshold was loosened to improve these timings. The corrected small-batch
size sweep is in [local-device-timings.md](local-device-timings.md).

A sustained flat-filter probe measured 1.63 ms initially and about 1.40 ms
later while the reported GPU clock rose from 1023 to 2092 MHz. Clock ramping,
batch size and competing work affect comparisons with short alternating
CPU/GPU timing rounds. No power or clock settings were changed. The size sweep
measures repeated warm API calls, not a guarantee of peak sustained throughput.

## Controlled hierarchical A/B

A follow-up isolated the refinement fix from coarse tiling. All three variants
used identical inputs from the teaser, n=4096, full windows, SNR=5.5,
fd=0.01, band=256, and the same supplied calibration. The pre-fix variant
changed only `refine_4096.spv` to its parent-of-429d5c2 version; the untiled
variant selected the existing tile-one coarse binary. No thresholds changed.
The public GPU `run()` call was timed, including output assembly, after 0.5 s
warmup per variant. Twelve rounds rotated/reversed variant order and used
50 ms timing blocks. Values are median milliseconds per batch.

| Batch | Before fix, tiled | Fixed, tiled | Fixed, untiled |
|---|---:|---:|---:|
| 16 × 64 | 0.07079 | 0.06350 | 0.06401 |
| 16 × 1024 | 0.31632 | 0.21756 | 0.22546 |

The large hierarchical batch takes 31.2% less time after the fix (1.45×
throughput). Tiling's additional end-to-end difference here is only 3.5%
and overlaps round-to-round ranges; this is not evidence for a large tiling
speedup. The small-batch tiling difference is negligible. Every variant
returned matching final peak indices/values and refined exactly 6.8359375%
of pairs. These comparisons measure retained tiling separately from repaired
refinement, rather than inferring either benefit from a CPU/GPU speed ratio.
Raw ranges are in `docs/measurements/hierarchical-ab-2026-09-26.json`.

## Larger presentation workload: 128 × 512

At 4096 points, this batch has 65536 correlations. With the same teaser input
construction, full window, SNR=5.5 and fd=0.01, the controlled GPU comparison
measured:

| Hierarchical path | Median ms per batch |
|---|---:|
| GPU before refinement fix, tiled | 0.614 |
| GPU fixed, tiled | **0.435** |
| GPU fixed, untiled | 0.467 |
| CPU, automatic band selection | 14.822 |

The refinement fix reduces GPU time by 29.2%. Tiling reduces time by another
6.9% versus the fixed untiled path (1.074× throughput), with non-overlapping
round ranges in this measurement. The complete GPU path is approximately
34.1× faster than the separately timed CPU path. CPU selects band 512 and GPU
band 256, so this device comparison includes their selection policies.

All GPU variants returned matching final peaks. Tiled variants refined 1944
pairs; untiled refined 1947 of 65536, a three-pair difference consistent with
numerical differences near the coarse gate. This is not an exactly identical
refinement workload and is recorded rather than hidden. All three use the
same coarse threshold. GPU timings used twelve rotating/reversed rounds,
50 ms blocks and 0.5 s warmup per variant; CPU used the same block and warmup
method separately. Raw results are in
`docs/measurements/hierarchical-ab-128x512-2026-09-26.json`.
