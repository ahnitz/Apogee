# CPU peak scan and codelet experiments — 2026-09-26

**No production kernel or dispatch changes are enabled.** Several candidates
improve AVX-512, but none passed the broader performance checks without a
repeatable regression. The useful deliverables are reproducible candidates,
measurements and new permanent tests for the peak-selection contract.

This follows `cpu-coarse-broadcast.md` and `cpu-int16-swar-study.md`. It evaluates
the first four follow-up opportunities: single-peak scans, final-stage fusion,
codelet scheduling, and AVX2 scalar broadcasts. A generated Q15 family remains
unimplemented; the earlier int16 study still applies. No calibration thresholds,
profiles, costs or precision choices are changed here.

## Experiments and decisions

All ratios below are baseline time / candidate time: above 1 is faster. These
are measurements on the Ryzen AI MAX+ 395, not guarantees for other CPUs.

| Candidate | Observed result | Decision |
|---|---|---|
| Register-resident single-bin peak scan | Minimal candidate's allocation-varied native runs: AVX3 1.073–1.276x; SSE4 0.989–1.071x. AVX2 size 64 / 16 templates fell to 0.903x despite no intended arithmetic change there. | Retain as an experiment. |
| Final FFT stage fused with peak reduction | Against the register-scan candidate: AVX3 0.745–0.982x, SSE4 0.912–0.981x; a few AVX2 512/1024 cases reached 1.04–1.07x. | Reject this implementation. |
| Earlier consumption of fused outputs | AVX3 0.756–0.965x, SSE4 0.896–0.990x against the register-scan candidate. | Does not rescue fusion. |
| Earlier split-radix output stores | Initial AVX3 sweep 1.009–1.091x against the register-scan candidate. Combined builds regressed some size-64 cases. Restricting the change to 32-point codelets reduced scope but did not make the whole candidate regression-free. | Keep the generator patch for further study. |
| Isolated AVX2 scalar-broadcast wrapper at 128–512 | 0.794–1.087x against production, including regressions in the staged size-64 fallback. | Reject. |
| Index-only and two-accumulator AVX2 scans | Some early runs won, but the combined candidate repeatedly lost at size 64 / 128 templates, including a 0.905x confirmation on another core. | Reject as a default. |
| 32-byte loop alignment on the old AVX2 scan | Native confirmation: size 64 / 16 templates 0.771x; 128 templates 0.748x. Also a 0.964x AVX3 case. | Reject. |

A positive coarse threshold matters. A scan that wins when every pair returns a
peak can lose when nearly everything is rejected. The full register-scan
candidate reached only 0.880x on AVX3 size 64 / 128 templates with a very high
threshold. The minimal candidate therefore retains the original scan for AVX3
size 64 with a positive threshold. That fixes one selection mistake, but does
not remove the independent AVX2 counterexample.

## What was implemented experimentally

The single-bin scan keeps maximum magnitude, index, real and imaginary values
in registers. It visits lags in natural order and uses the original strict
comparison, so an equal maximum retains the earliest lag. It avoids the generic
scan's per-sample bin calculation and accesses to bin accumulator arrays.
Dispatch was tried both inside the general scan and at the pair-batched entry
point. The latter preserves the general scan's implementation and leaf status.
Only measured x86 targets were opted into the minimal candidate.

The fusion prototype generates separate 16/32-point twiddle codelets whose final
stores call an inlined peak accumulator. The first product stage stays unchanged.
It eliminates the last output-buffer write/read round trip for two-level small
transforms. Because outputs arrive in transposed lag order, it explicitly merges
equal magnitudes by their earliest index. It passes correctness checks, but the
extra accumulator state, window tests and comparisons do not pay for themselves.
An alternate version consumes each root quartet sooner; it still loses overall.

The scheduling prototype writes each completed split-radix root quartet before
computing the next quartet. All input loads have completed in the recursive
calls, so this does not overwrite unread input or change arithmetic expressions.
The narrowed generator patch enables this only for AVX3 32-point codelets.
Disassembly of that prototype shows:

| Codelet | Baseline instructions / stack-address operands | Candidate |
|---|---:|---:|
| AVX3 `fftsr32_tw` | 890 / 149 | 872 / 100 |
| AVX3 `fftsr32_prod_broadcast` | 1036 / 162 | 1061 / 120 |

Stack-address operands include arguments and local arrays, not just register
spills. Fewer such operands, or fewer arithmetic instructions, did not prove an
overall win. Normalized AVX2/SSE4 radix-32 twiddle and radix-64 product instruction
sequences remained unchanged in these comparisons. Code addresses and layout
can still move. The experiments establish performance sensitivity; they do not
prove a particular instruction-cache, predictor or cache-aliasing mechanism.

## Measurement controls and limitations

The native baseline is commit `a5a63b6`, including the earlier AVX-512 broadcast
optimization. A clean rebuild produced exactly the same SHA256 as the retained
baseline binary. Native source was unchanged in the intervening repository
commits. Benchmark processes use the same frozen Python package on both sides
so concurrent Python/model work does not contaminate the comparison.

`tools/bench_cpu_broadcast.py` alternates persistent baseline/candidate workers
and requires their output bytes to match. It now supports restricted windows,
arbitrary bin sizes, positive thresholds and a repeat-count override. Tests
include real automatic dispatch, sparse hierarchical refinement, general bins,
mostly rejected pairs and larger transforms. `tools/bench_cpu_peak_native.py`
also compares the two C APIs within one process, timing through a native bridge
rather than Python calls. It alternates timing and allocation order, keeps five
plans per implementation alive, and checks index, real, imaginary and magnitude
fields exactly. These different boundaries can reveal losses hidden by Python
allocation/call overhead.

There was substantial concurrent work on the machine: CPU cost regeneration and
a parallel bank-building job. One busy worker ran on CPU 22, the SMT sibling of
benchmark CPU 6. Confirmation moved to CPU 15, whose sibling is CPU 31. This was
not a fully reserved machine: frequency, physical cache placement and unrelated
process scheduling were not controlled. Some apparent gains changed between
runs. However, the decisive losses persisted in allocation-varied confirmation
runs on the other core. They are not dismissed as noise, nor is shared-machine
noise used as proof of a universal architectural limit.

## Correctness and permanent tests

The prototypes passed the selected correctness checks; rejecting them is a
performance decision. The combined scan/scheduling candidate passed 583 tests
with 241 skips in the frozen `b25d6a8` test/package snapshot, including the new
CPU tests. GPU-dependent checks skipped in that CPU validation run. Each of six
ISA / `MF_SRPROD` combinations passed 108 targeted tests, including the mandatory
CPU 0.01/0.001 calibration-transfer guard. This does not claim GPU validation of
a new shipped kernel: no new kernel is shipped.

`tests/test_cpu_single_peak.py` stays in the standard suite and needs no GPU.
It covers:

* Sizes 64–1024, single-template and partially occupied/unaligned packets.
* Equal maxima, exact threshold equality, zero data and empty peak results.
* Full, restricted, odd-length and one-sample windows.
* Alternating single-bin and general-bin calls on the same plan.
* An exact period-four correlation with equal peaks at lags 1 and 2, which
  catches an incorrect tie merge between odd/even accumulators.

The ten new tests were rerun against the unchanged production binary under
AVX3, AVX2 and SSE4, with split-radix product loading both enabled and disabled:
all six runs passed. All benchmark comparisons require matching outputs; no
NumPy FFT was added to production or to these new tests.

## Reproduction and saved artifacts

The audit directory is `docs/audits/cpu-peak-scan-2026-09-26/`. JSON arrays are
compacted one measurement row per line; all individual timing samples remain.
Important files:

* `scan.json`: first general single-bin specialization sweep.
* `fusion*.json`, `schedule.json`, `broadcast.json`: isolated experiments.
* `shipping-*.json`: the provisional combined candidate, **not shipped**.
* `idle-core-*.json`: confirmation of that candidate on CPU 15.
* `minimal-*.json`: only the AVX3/SSE4 scan candidate, without scheduling changes.
* `loop32-native.json`: the rejected loop-alignment experiment.
* `rebuild-control.json`: byte-identical baseline rebuild timing control.
* `environment.json`: compiler, hardware, snapshot and binary identities.

The patches are research artifacts, not active library code. Apply them to the
`a5a63b6` native sources in a separate scratch checkout/build:

* `candidate-single-peak.patch`: minimal register scan and dispatch.
* `candidate-loop32.patch`: same, with the rejected AVX2 loop-alignment attribute.
* `candidate-scan-schedule.patch`: combined scans plus the narrowed generator
  change; regenerate with `(cd src && python gen.py)` before building.
* `rejected-fusion.patch`: original fused final-stage prototype, including its
  generated private codelets.

Example measurement commands (choose an idle core appropriate to the host):

```sh
PYTHONPATH=/path/to/baseline taskset -c 15 python tools/bench_cpu_peak_native.py \
  /path/to/baseline /path/to/candidate /tmp/native.json
python tools/bench_cpu_broadcast.py /path/to/baseline /path/to/candidate \
  --output /tmp/automatic.json --cutoff 0 --rounds 9 --repeats 500
python tools/bench_cpu_broadcast.py /path/to/baseline /path/to/candidate \
  --output /tmp/rejected.json --kinds flat --threshold 1000000
python tools/bench_cpu_broadcast.py /path/to/baseline /path/to/candidate \
  --output /tmp/bins.json --kinds flat --bin-size 17 --window-fraction .6
```

The next useful experiment is isolating per-target code generation/layout before
retrying the small scan or output-store schedule, with both native and Python
API checks and the high-threshold workload included from the start. That is a
hypothesis to test, not an established fix. Enlarging the Q15 implementation or
accepting a narrower correctness check would not resolve these regressions.
