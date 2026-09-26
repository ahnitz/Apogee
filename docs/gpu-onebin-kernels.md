# Large one-bin GPU kernels — 2026-09-26

This implements a measured kernel-level optimization from the binary audit.
Full-precision flat and listed-refinement Vulkan kernels at lengths 16384,
32768 and 65536 now have a one-output-bin build. The host selects it only
when the searched window produces exactly one bin, including oversized bin
widths. Multiple-bin calls keep the original general kernels. Smaller lengths
keep their original kernels because no robust benefit was established there.

`SINGLE_BIN` constant propagation removes the general bin tables, integer
binning and associated live ranges. The FFT arithmetic, search-window mask,
threshold semantics and single-writer tied-peak election are shared unchanged.
The specialization is generated from the same function, not a separate FFT.
Both 64 KiB and 32 KiB staging builds ship. Metal continues to use its existing
peak kernels; an unmeasured Metal optimization is not enabled by this patch.

## Binary evidence

| Flat length | General instructions | One-bin instructions | General spilled VGPRs | One-bin spilled VGPRs |
|---:|---:|---:|---:|---:|
| 16384 | 4537 | 3471 | 27 | 18 |
| 32768 | 12771 | 9783 | 1248 | 974 |
| 65536 | 48156 | 38371 | 7415 | 6407 |

Refinement has the same changes plus approximately five instructions for
reading the survivor list. These are RADV static/compiler counts, not dynamic
traffic measurements. Large FFT scratch allocation remains substantial: this
reduces work and spills, but does not replace the large-transform decomposition
or optimize the forward FFT. That broader redesign remains a separate task.

Every pre-existing SPIR-V file retained by this change is byte-identical to
its previous version except `pack_coarse.spv`. Thus coarse fp16 arithmetic,
forward FFT and general/multiple-bin FFT instruction streams are unchanged.

## Measurements

Radeon 8060S, warmed pipelines, nine alternating rounds, identical input and
bit-identical output checks. Rows means that many data rows and templates,
so 64 rows measures 4096 pairs. Selected results:

| Length | Rows | Path | General ms | One-bin ms | Latency reduction |
|---:|---:|---|---:|---:|---:|
| 16384 | 16 | flat | 0.176 | 0.156 | 11% |
| 16384 | 64 | flat | 1.946 | 1.637 | 16% |
| 16384 | 64 | hierarchical | 2.078 | 1.723 | 17% |
| 32768 | 16 | flat | 1.348 | 1.048 | 22% |
| 32768 | 64 | hierarchical | 21.939 | 17.210 | 22% |
| 65536 | 16 | flat | 21.030 | 18.469 | 12% |
| 65536 | 64 | flat | 264.822 | 194.217 | 27% |
| 65536 | 64 | hierarchical | 262.576 | 193.652 | 26% |

Hierarchical measurements deliberately admit every pair to isolate refinement.
Sparse workloads will see a smaller total benefit. The portable 32 KiB builds
were also checked on this GPU: most measured 6–19% faster; one short 16384
hierarchical case initially measured 2.3% slower. A repeat with 31 alternating
rounds of five calls resolved this: portable 16384 measured 3–4% faster for
one pair and 10–12% faster for 16x16 and 64x64 pairs on both paths. This is
not evidence that every workload on every device improves.

A tiny-call check against the *previous runtime and binaries*, 31 alternating
rounds of 20 calls, resolved an initially noisy 16384 one-pair result:
58.86 → 53.59 µs (9% lower latency). At 32768 it was 161.83 → 125.84 µs (22%).
Unchanged 4096 cases differed by 0.1–0.3%; the unchanged 16384 four-bin case
measured +2.7% in that run despite identical shader code and unchanged cached
execution logic. Timings this small should not be read as universal guarantees.
Full raw timings are in [measurements](audits/onebin-kernels-2026-09-26/measurements.json).

## Other binary-preserving/neutral cleanup

- Eleven identical compaction SPIR-V files became `compact.spv`, used by every
  manifest entry and a common pipeline-cache key. The canonical bytes are
  identical to the previous modules. This removes 27,000 duplicate bytes.
- Coarse extraction uses shifts/masks for its positive power-of-two band,
  reducing the Radeon packing kernel from 61 to 39 instructions. The binary
  audit's paired measurements were neutral, with bit-identical output in both
  fp16 and fp32 output modes. The shared source generates both backend artifacts.

The twelve new one-bin files add 402,776 bytes before wheel compression.

## Regression coverage

`test_onebin_kernels.py` verifies artifact presence, canonical compaction,
portable selection, and exact specialized/general output equality. It covers
flat and hierarchical dispatch, partial windows, oversized bin widths,
multiple-bin fallback, empty outputs, and both staging sizes. Existing tied-peak,
series/shared-buffer, independent FFT and calibration-FDR tests remain active.

## Validation result and concurrent work

The new kernels passed **833 tests, with 10 skipped and 1 expected failure**,
including mandatory GPU FDR coverage, in an isolated package copy using the
committed Python calibration API. The shared checkout's concurrent uncommitted
`choose_threshold()`/`gatemodel.py` work changes the table-refusal contract and
produced five unrelated failures. All five disappear with the committed API;
that concurrent work was neither reverted nor included in this change.
