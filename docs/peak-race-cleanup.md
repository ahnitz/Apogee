# GPU peak race and audit cleanup — 2026-09-26

## Peak output ownership

The GPU peak reduction now elects one register slot per bin before that
thread writes both the index and complex value. Exact ties may still choose
any lag, but the value always belongs to that lag. This applies to full
precision flat/listed refinement and the packed-half coarse variants.

Single-bin reduction uses a wave-local minimum followed by a shared atomic
minimum (separate per-pair atomics for packed workgroups). Many-bin reduction
reuses the magnitude scratch as winner scratch after retaining candidates in
registers. No extra shared-memory allocation or host synchronization is added.

Regression tests use equal-magnitude, different-phase peaks, check the value
at the returned lag, and cover windowing, many bins, empty results, large
radices, and hierarchical compaction/refinement. The original length-16384
reproducer reported 117 mismatches in 12,288 pairs before the fix and zero
afterward on Radeon 8060S.

## Performance

Alternating old/new warmed pipelines, 64 data rows by 64 templates, median
of nine rounds of three calls, measured approximately:

| Length | Bin width | Old | Fixed | Change |
|---:|---:|---:|---:|---:|
| 1024 | 1024 | 0.113 ms | 0.111 ms | -2% |
| 4096 | 4096 | 0.364 ms | 0.371 ms | +2% |
| 16384 | 16384 | 1.796 ms | 1.936 ms | +8% |
| 4096 | 64 | 0.607 ms | 0.637 ms | +5% |

The synchronization needed for single-writer correctness has a measurable
cost. Attempts to fold winner selection into the magnitude pass worsened
code generation; a wave-summary alternative did not improve the large case.
The simpler implementation is retained. These are local workload timings,
not a guarantee for other devices; Metal performance remains unmeasured here.

## Cleanup

- Metal libraries, functions, descriptors, pipelines, queues and enumerated
  devices now have balanced owned references. Dispatch uses autorelease
  pools; deferred forward commands retain their explicit lifetime. Mocked
  reference accounting covers success, failure, fallback and repeated teardown;
  a macOS-only test repeats creation, dispatch and destruction.
- The main shader build includes forward and packing kernels, with manifest
  entries and source hashes checked by installation tests. The old forward
  build command delegates to the complete build. All Metal sources can be
  compiled to metallibs on an Apple build host.
- Removed write-only CPU fields and the obsolete Metal gated-kernel mapping.
  Archived unused GPU prototypes under `src/gpu/draft` and the unused model
  table under `tools/regen`; CI no longer regenerates that historical table.
  Updated dispatch and calibration descriptions. Calibration remains explicit:
  a provided file, or a user-provided coarse size and threshold.

The CPU coarse-gate boundary bug remains open. The user deprioritized binsizes
above 32 bits. Neither is silently counted as fixed by this cleanup.

## Validation result

The native extension was rebuilt, all production shader artifacts regenerated,
and the full suite ran with Radeon 8060S access: **755 passed, 6 skipped**.
The skipped tests include platform-specific Metal execution; macOS CI is the
runtime check for those changes. `git diff --check` is clean.

## Fast coarse-calibration transfer regression

`tests/test_coarse_fdr.py` directly compares CPU coarse peaks with every
shipped Vulkan option at bands 64, 128, 256, 512, 1024 and 2048: fp32,
packed fp16, pair-packed, template-tiled, and the separate fp32 tiled kernels.
That is 39 implementations (30 fp16 variants, six fp32, three tiled).
On Metal it checks the production fp32 coarse implementation at those sizes.
Larger coarse sizes are not part of this quick sweep.

Each size uses 32,768 seeded independent noise/injection trials and four
spectral profiles with different widths and phases. Lags lie on an 8-times
finer grid than the coarse transform. An independently evaluated sample at
the injected fine lag selects signals known to exceed the fine threshold
5.5; this avoids a full refinement FFT and leaves at least 15,000 detections.
The comparison therefore covers a defined subset of detectable injections,
not every signal that might trigger elsewhere in the full lag window.

CPU empirical quantiles set thresholds for 0.01 and 0.001 false dismissal.
The GPU must use those exact thresholds. Paired admission disagreements
(including disagreements that cancel in the aggregate rate) may not exceed
12.5% of the CPU dismissal count, rounded up to an integer. A separate
0.6% pointwise magnitude bound catches scale drift away from these particular
thresholds. The diagnostic includes threshold, counts, rates and kernel;
JUnit properties retain each measured comparison. A deliberately biased
synthetic result verifies the guard rejects a small systematic scale drift.

This is a calibration-transfer regression, not an independent certification
of the shipped tables' population false-dismissal probabilities. Finite tails
and limited spectral profiles cannot establish that claim. No thresholds are
recalibrated independently for the GPU, and no runtime code changes are needed.
Validation on Radeon 8060S: **7 passed in 19.71 seconds**.
