# Binary kernel review — 2026-09-26

There are optimization opportunities, but no general zero-cost accuracy
upgrade established by this review. The clearest performance issue is scratch
spilling in the large GPU transforms. The clearest zero-kernel-cost cleanup is
the duplicated compaction module. A tested integer-index simplification removes
instructions but does not measurably accelerate the packing stage.

## Scope and evidence

Hardware: Ryzen AI MAX+ 395 / Radeon 8060S, Mesa RADV
25.3.6-3.fc43. Native Python 3.13 extension, active AVX3 with AVX2 and SSE4
also present. Core sources and shipped SPIR-V are unchanged between `bdfdad6`
and the reviewed checkout `c444b63`; concurrent calibration research was left
alone. The exact extension and driver hashes are in the measurements file.

- Disassembled all 117 `ap::N_*` CPU functions: generated FFT/product/twiddle
  codelets, element transforms, forward/inverse paths, peak scans and helpers.
- Inventoried all 95 shipped SPIR-V files. Captured actual Radeon assembly
  for all 92 variants within the 1024-thread workgroup limit. The three larger
  packed experiments are not runnable on this device; they are not selected
  by production coarse dispatch. One was compiled before the limit check and
  remains explicitly marked invalid in the inventory.
- Covered flat correlation, coarse fp16 and tiled variants, listed refinement,
  forward FFT, compaction and coarse packing, including portable LDS variants.
- Metal generated source shares the relevant algorithms, but this is **not**
  native Metal or ARM/NEON disassembly. No Apple machine-code performance claim
  follows from the Radeon/x86 results. Apple CI executing a kernel is not a
  substitute for inspecting its native binary.

[GPU inventory](audits/binary-kernels-2026-09-26/gpu.csv),
[CPU inventory](audits/binary-kernels-2026-09-26/cpu.csv), and
[measurements](audits/binary-kernels-2026-09-26/measurements.json).

Static instruction counts are not dynamic operation counts. Branch counts
include uniform branches and bounds checks; they do not measure warp divergence.
CPU stack operands include arguments and local arrays, not just spills. RADV's
reported scratch allocation is recorded verbatim, not multiplied into a claimed
per-dispatch traffic total. Occupancy figures are compiler resource limits,
not a measurement of sustained occupancy or utilization.

## 1. Large GPU transforms: the first performance target

Production flat kernels on this driver:

| Length | Instructions | Spilled VGPRs (driver report) | Scratch size (bytes) |
|---:|---:|---:|---:|
| 4096 | 3642 | 0 | 0 |
| 16384 | 4537 | 27 | 1280 |
| 32768 | 12771 | 1248 | 30720 |
| 65536 | 48156 | 7415 | 88320 |

Listed refinement has essentially the same profile: the extra survivor-list
load adds about five instructions. The normalized forward transform is worse
at the largest sizes: 14,465 instructions / 32,256 scratch bytes at 32768,
and 60,713 / 89,600 at 65536. At 65536 its assembly contains 11,278 static
scratch stores and 8,432 scratch loads. These are concrete memory operations,
not a source-level guess about register pressure.

The wide radix keeps much more state per thread while the group remains 1024
threads. All these large full-precision variants are allocated only 96 VGPRs
per thread by this driver. The existing 32 KiB LDS variants do not solve it:
65536 flat grows to 74,744 instructions and 90,368 scratch bytes.

**Candidate:** split the largest transform across workgroups/dispatches or
redesign register lifetimes and exchange scheduling. Start with 32768/65536;
16384 may respond to a smaller one-bin specialization. This has substantial
potential, but extra dispatch/intermediate traffic can lose on small batches.
It is not a promised zero-regression rewrite. Preserve current kernels as
measured alternatives until batch/size/device crossover points are established.

## 2. Coarse kernels: retain precision and dispatch distinctions deliberately

The actual production fp16 choices are spill-free here. Examples:

| Variant | VGPRs | Instructions | Driver subgroup limit/SIMD |
|---|---:|---:|---:|
| 128, PPG4, tile2 | 120 | 1836 | 12 |
| 256, PPG2, tile2 | 120 | 1866 | 12 |
| 512, tile4 | 216 | 4179 | 7 |
| 1024, tile2 | 108 | 3442 | 14 |
| 2048, untiled | 84 | 2439 | 18 |
| 16384, untiled | 96 | 3210 | 16 |

The 512 tile4 kernel really uses packed arithmetic: 1160 static `v_pk_*`
instructions. The untiled 512 kernel still contains scalar half/conversion
work (232 packed instructions among 484 instructions whose names contain
`f16`). This is evidence to investigate data layout, not proof that tiling
should be enabled more widely. Tile4 already spends enough registers to
reduce its resource-limited wave count; the experimental PPG4/tile4 variant
spills. Fewer loads and more packing can trade against occupancy.

**Candidate:** reconsider tile depth using current binaries and realistic
bank shapes, including uneven banks that use fallback kernels. Do not remove
per-pair reduction isolation or tie-winner election to simplify these paths:
those distinctions enforce correctness. Do not merge fp16 with fp32 merely
to unify source; that changes the calibrated statistic and throughput.

## 3. A proven binary-identical simplification: compaction

All eleven `compact_<length>.spv` files are **byte-identical**, each 2700 bytes.
The shader does not depend on transform length. Its machine code has 60
instructions, 12 VGPRs, no LDS and no scratch. Length-specific pipeline cache
keys can also cause the same kernel to be compiled/cached repeatedly in a
context that uses multiple lengths.

**Candidate:** ship one canonical compaction module and cache it independently
of transform length; preserve any filename compatibility that is required.
This removes 27,000 duplicated SPIR-V bytes and duplicate pipeline setup.
The kernel can remain byte-identical, so this requires no arithmetic or GPU
throughput tradeoff. Pipeline ownership and teardown must still have exactly
one owner—aliasing cache entries without fixing teardown would double-free.
Metal source deduplication is plausible but native binary identity was not
measured here.

A second, less certain opportunity is subgroup-aggregated survivor atomics.
Current code has one atomic add for each surviving pair. That could matter at
high survival, but sparse survival and tiny batches might lose. Replacing
`length(z) >= threshold` with a squared comparison is also **not** automatically
safe: rounding, overflow and equality boundaries can change calibration gates.

## 4. Packing: fewer instructions, measured neutral performance

The coarse band is a positive power of two, but `packCoarse` uses general
runtime division/remainder. The following isolated candidate preserves the
address mathematically for the supported bands:

```diff
- data[(i / band)*n + i % band]
+ data[(i >> firstbithigh(band))*n + (i & (band-1))]
```

Radeon output: **61 → 39 instructions**, **308 → 208 code bytes**;
VGPR count remains 12 and both versions have zero scratch. The runtime mode
branch (`packed`) is uniform, so it is not divergent lane work worth removing.

Four alternating tests, 11 rounds, 100 ordered dispatches per submission:

| N / band / rows / mode | Original µs | Candidate µs |
|---|---:|---:|
| 4096 / 128 / 64 / fp16 | 1.165 | 1.166 |
| 16384 / 512 / 256 / fp16 | 3.021 | 3.005 |
| 16384 / 4096 / 256 / fp16 | 42.721 | 42.652 |
| 4096 / 256 / 64 / fp32 | 1.280 | 1.284 |

Outputs matched bit-for-bit. All timing differences are within noise;
submission, barriers and memory work dominate these cases. This is a reasonable
simplification candidate, **not** an established speedup or a universal
zero-regression guarantee. The production source/artifacts were not changed.

## 5. CPU kernels: address/scratch scheduling, not missing SIMD

The CPU kernels are vectorized. AVX3/AVX2 use fused arithmetic; SSE4 lacks FMA
as expected. FFT codelets themselves are branch-free. The full scans have
branches for windows, bins and rare maximum updates; unconditional masked
updates are not clearly cheaper than the existing rare-update branch.

For the retained AVX3 Stockham `fft64_prod` alternative, 2786 static
instructions include 424 `vmovaps`, 256 `vmovups`, 270 `mov`, 206 `lea`,
252 `vmulps` and 288 FMA-family instructions. Some moves are memory accesses,
so the whole `vmovaps` count must not be described as register renaming.
The default AVX3 split-radix product codelet has 2451 instructions and 526
stack-address operands versus 262 in the Stockham alternative. Fewer arithmetic
operations do not establish a faster schedule when live ranges are longer.

**Candidate:** register-lifetime-aware generator scheduling, address hoisting,
and smaller intermediate codelets where stack traffic dominates. Measure
separately for AVX3/AVX2/SSE4; the code already selects different decomposition
families for a reason. Removing those differences is not justified by code
size alone. The dormant interpolation helper is also still compiled for each
ISA, but its internal API/callers should be audited before deleting it; it is
not consuming steady-state filter time when unused.

Exploratory `MF_SRPROD=0/1` runs on the same inputs returned correct indices in
all 18 ISA/size cases, with maximum relative peak-value errors between
1.54e-7 and 2.61e-7 against complex128 FFTs. Neither mode consistently improves
accuracy. These CPU timings ran in separate processes and are retained as
exploratory data, not evidence for changing dispatch: observed run-to-run drift
is too large to claim a free global win.

## 6. Accuracy and implementation divergence

No zero-cost accuracy change is established. Explicit FMA is already present;
blanket reassociation or fast-math can change ties, thresholds, overflow and
NaN handling. Promoting fp16 coarse arithmetic to fp32 changes throughput and
register use. Compensated or scaled magnitude evaluation adds work unless a
specific replacement can be shown to compile equivalently.

Safe direction: consolidate genuinely identical artifacts and keep shared
FFT helpers shared. For math changes, require the paired 0.01/0.001 FDR checks,
independent CPU reference, normalization/batching tests and tied-index/value
checks, plus an alternating timing matrix. Exact machine-code identity can
prove no kernel-throughput change for deduplication; a small benchmark can
only establish no *measured* regression on that hardware/workload.

## Reproducing the inventory

`tools/audit_kernel_binaries.py --capture-gpu` compiles all shipped shaders
within the device's workgroup limit and emits tagged driver assembly when run
with `MESA_SHADER_CACHE_DISABLE=1 RADV_DEBUG=shaderstats,asm`. Redirect stderr
to a file, then pass it through `--gpu-log FILE --output audit.json` to combine
GPU resources with native CPU disassembly. It requires GNU objdump for the CPU
part and a RADV device for this GPU dump format. The local conda Python also
needed `LD_PRELOAD=/usr/lib64/libstdc++.so.6`.

For the packing experiment, compile the isolated source edit with
`slangc candidate.slang -target spirv -entry packCoarse -stage compute -O3
-o candidate.spv`, then run `tools/bench_pack_indexing.py --candidate-spv
/path/to/candidate.spv`. No production source patch is needed to repeat it.

Accuracy validation of the audited production binaries: **42 passed in 19.82s**
for coarse FDR transfer (mandatory GPU), calibration invariants and tied peaks.
The packing candidate separately passed bitwise output comparisons in both
modes; it remains an experiment, not a shipped change.
