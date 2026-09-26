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
