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
