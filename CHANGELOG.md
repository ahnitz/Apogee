# Changelog

This project is pre-1.0 and moving fast. Alpha releases are for people who
want to try it and report back; interfaces may still change.

## 0.1.0a2 (unreleased)

The headline is that there is now a GPU. Both backends are generated from a
single Slang source, so the two do not drift: Vulkan/SPIR-V everywhere, and
native Metal on Apple silicon.

### Added

- **GPU backends.** Vulkan (SPIR-V) and Metal, from one Slang source.
  `device="gpu"` runs the whole API, flat and hierarchical, with no method
  silently falling back to the CPU. `device="auto"` picks a GPU when there
  is a real one.
- **Apple silicon.** Every transform length from 1024 to 16384 runs on an
  M2 and agrees with the CPU index for index. Wheels carry compiled kernels,
  so installing one is enough -- no toolchain, no separate build step.
- **Per-device cost tables and per-algorithm accuracy tables.** Cost is a
  property of the machine and accuracy is a property of the algorithm, so
  they resolve separately: `cost-<arch>.txt` by device, `accuracy-gpu.txt`
  by code path. Shipped: `cost-gfx11.txt` (RDNA 3/3.5), `cost-apple.txt`,
  `accuracy-gpu.txt` measured with the GPU actually filtering.
- **`MatchedFilter.run_series`** (`ap_mf_run_series`). The wide interface --
  one call per segment instead of one per block -- previously existed only on
  `HierarchicalFilter`, which is backwards: hierarchical needs a reference
  spectrum and the `(n, snr, fd)` tables, flat needs neither, so flat is what
  a caller outside gravitational-wave search reaches for first. Blocks sharing
  a window are filtered together up to the plan's own `ndata`, which is the
  grouping knob and deliberately the only one.
- **`UnsupportedSize`**, so a length a device genuinely cannot run is a
  skip with a reason rather than a failure with none.
- DLPack ingest, device selection, and a standing CPU/GPU scoreboard.
- `tools/gpu_roofline.py`: measures a device's real FMA and add rates and
  places the filter against them.

### Performance

- Flat GPU filter: **44-61x** a CPU core, after fixing per-call churn and
  the exchange staging.
- Metal gets its own threadgroup-staging column: **2.01x at n=4096** on an
  M2, taking it from 26% to 52% of that chip's measured add rate. The same
  change costs the Radeon 31%, which is why it is a second column and not
  an edit to the first.
- Peak readback moved off write-combined memory.

### Fixed

- **Heap overflow in `run_series`, on the shipped hierarchical path.** The
  output is addressed at a single stride taken from the first block, but the
  bin count was recomputed per group, so a window yielding fewer bins wrote
  into the next block's row and off the end of the buffer. Ordinary
  overlap-save input reaches it -- the ragged edge blocks `run_series` exists
  to accept are exactly the short ones -- and it aborted the interpreter
  rather than failing. Now refused with a clear error, in C and in Python,
  on both filter classes.
- The hierarchical coarse-template cache never hit -- it was keyed on the
  `id()` of a fresh view.
- `_ensure` discarded a pinned configuration on the GPU path.
- `device="auto"` chose the CPU on a Mac, because it only asked Vulkan.
- The GPU accuracy sweep wrote the margin where the GPU never read it and
  so measured every margin at 1.0. It now refuses to start if two margins
  agree.
- Metal: `hier_peaks` implemented, oversized bin counts split, and the
  32 KB threadgroup limit respected with a portable kernel variant rather
  than a pipeline failure that named nothing.

### Known limitations

- **n=16384 on Apple silicon is slow** -- 12.97 us/pair on an M2, 13% of
  that chip's add rate, against 32-52% at every shorter length. It runs and
  it is correct; it is not yet fast. An R=32 decomposition is the candidate.
- The Apple cost table is keyed on `apple`, not on a specific M-series
  chip, so an M4 uses an M2's relative costs. Better than the CPU table it
  replaces, not as good as its own.
- The margin axis of the GPU cost tables is nearly flat: on the measured
  configurations the coarse gate dismisses the same pairs at every margin,
  so selection across margins is driven by the accuracy table alone.
- `tools/gpu_roofline.py` is Metal-only, so the Radeon's *achievable*
  ceiling is not measured -- only its achieved rate.

## 0.1.0a1

First alpha: single-threaded batched matched filter with peak-only output,
a hierarchical two-stage variant, and Highway multi-target SIMD dispatch on
the CPU.
