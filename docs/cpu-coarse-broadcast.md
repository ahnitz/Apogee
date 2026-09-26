# CPU coarse-stage data broadcasts

Measured on Ryzen AI MAX+395, September 26, 2026. This change keeps fp32
arithmetic and coarse thresholds unchanged. It removes a data-layout conversion
from the AVX-512 pair-batched transform. It does not implement int16.

## Implementation

Previously `run_pairs_pb` expanded each scalar data spectrum into `AP_W`
identical lanes per element. Product codelets then loaded these full vectors
for each template group. The new codelets broadcast scalar data directly while
still loading templates as vectors. At band 1024 this saves 128 KiB of temporary
buffers per AVX-512 pair-batched plan, plus their write/read traffic.

The generator preserves the existing staged codelets verbatim and derives
separately named broadcast codelets by changing only data loads. Both paths
share the dispatch and transform structure in `product-inl.h`. The dispatch
helper is private, so unsupported variants are eliminated at compile time.
No duplicate butterfly math is maintained by hand. The matched-filter plan
keeps its original structure layout; absence of the staged buffers identifies
the direct-load path.

Enable direct broadcasts only on AVX-512. AVX2, SSE4 and ARM retain staged
execution. Template packing, FFT arithmetic, scan, calibration and the existing
balanced/pair-batched selection policy are unchanged. CPU cost rows measured
before this change should be remeasured against the new extension: they remain
usable but can misprice the now-cheaper coarse stage. Concurrent cost-table
and calibration-model work is excluded from this patch.

## Performance and rejected variants

`tools/bench_cpu_broadcast.py` compares isolated package builds in persistent
subprocesses, alternates order each round, and requires identical output bytes.
The final baseline was rebuilt from `0bfb999` with the same compiler and flags.
The final sweep has eight data rows, 16/128 templates, and bands
64/256/512/1024. Hierarchical timings use seeded Gaussian spectra and a measured
threshold admitting approximately 1% of noise pairs (1.56% for the smallest
bank). This is a timing workload, not a signal-dismissal certification.

Seven alternating rounds, median paired throughput ratios at bands 256–1024:

| Workload | AVX-512 speedup |
|---|---:|
| Pair-batched coarse-sized transform | 1.08–1.44x |
| Hierarchical, spectra already ingested | 1.09–1.30x |
| Automatic dispatch, both banks re-ingested each call | 1.02–1.09x |

The first two rows force pair batching to isolate the kernel. The third uses
the production automatic policy and includes template ingestion every call.
When all pairs are admitted, refinement dominates and gains can approach zero.
There is no universal end-to-end gain. Final AVX2/SSE4 results are near parity
(roughly -1.4% to +6% across the sweep), not an improvement claim for those ISAs.
No ARM performance claim is made.

Several plausible implementations were rejected:

* Broadcasting everywhere regressed larger SSE4 banks.
* Templating the existing codelets changed compiler code generation even for
  the staged fallback. Band 64 lost up to about 30%. Preserving the original
  non-template codelets fixed the SSE4 regression.
* Mixed AVX2 dispatch improved bands 256/512, but its band-64 fallback still
  regressed. This patch leaves AVX2 entirely staged.
* Retaining an extra representation flag changed the plan layout. Using the
  existing buffer pointers instead keeps the old layout and avoids that extra
  state. The final fallback timings recovered near baseline.

Normalized disassembly of the original staged radix-64 product codelets matches
baseline on AVX3, AVX2 and SSE4, including instruction counts (2787, 3026 and
4258 respectively). This comparison normalizes relocation addresses and omits
padding; it does not claim the entire extension is byte-identical.

Raw results are in `docs/audits/cpu-coarse-broadcast-2026-09-26/`:
`steady.json` and `ingest.json` describe the final build; `rejected-template.json`
and `rejected-mixed-avx2.json` document the intermediate regressions. All samples
are retained, including slower cases. `environment.json` records build context.

## Validation

New standard-suite tests cover distinct scalar data rows, repeated updates,
unaligned template subsets, partially occupied groups and restricted windows
at lengths 64 through 1024 against a double-precision oracle.

The existing calibration-transfer test normally uses only four templates, which
does not select pair batching at the larger bands. Its mandatory CPU reference
case now also explicitly checks pair-batched execution, using the same seeded
32768 trials and paired 0.01/0.001 dismissal-rate guards. This runs without GPU
hardware in ordinary CI. Existing GPU comparisons remain part of the suite.

Validation uses an isolated package and test snapshot at committed `600cd5c`
plus this patch. The shared checkout's ongoing API/model/table rewrite is not
mixed into kernel validation. Both split-radix settings are checked on each
x86 target. The final full suite passed **840 tests**, with 10 skips and one
expected failure, including required Radeon 8060S GPU coverage. Each of the
six ISA/split-radix combinations passed 65 targeted tests (three GPU skips).

## Int16 remains a separate experiment

A real Q15 implementation must beat this faster fp32 baseline, including
input/product scaling, widened magnitude scans, partial batches, ingestion and
refinement. Lane count alone is not a measured throughput gain.

`tools/coarse_fixed.py:q15_ifft` adds/subtracts in int64 before shifting and
clipping. It is a numerical model, not an instruction-accurate int16 simulation.
For example, two representable values of 20000 sum to 40000: wide addition then
halving gives 20000, while wrapping int16 addition then halving gives -12768.
Saturating instead is also wrong. Complex twiddle rotation adds component
headroom requirements.

The native design must specify where it halves or widens intermediate sums,
prove overflow behavior, and remeasure rounding and admission decisions.
Sampled errors of 0.01% are not a universal bound or proof of calibration-table
transfer. Extend the paired 0.01/0.001 guards to any eventual Q15 implementation,
plus coherent, cancellation, zero-input and high-dynamic-range cases.
