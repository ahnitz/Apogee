# Library cleanup and calibration contract

The hierarchical execution engine now has one coarse gate. It reads a threshold
from the supplied measured files (shipped files by default), or the caller
explicitly sets **both** `band` and `set_coarse_threshold(value)`. Missing
calibration raises; no Rice model, recovery-factor calculation, compiled-table
fallback, or below-grid SNR/budget clamping remains in execution. Final detection
thresholds do not silently change the coarse gate. `set_coarse_threshold(None)`
returns to file lookup. An explicit gate has the false-dismissal behavior chosen
by its caller, rather than a library budget guarantee.

```python
f = matchedfilter.HierarchicalFilter(4096, band=512, device="gpu")
f.set_coarse_threshold(4.0)
# No calibration file or reference is needed for this explicit mode.
```

Without a reference, coarse template normalization uses each template's own
in-band fraction on both devices. With a reference, it uses that reference.
Changing or clearing the reference now rescales templates already ingested on
CPU as well as GPU. `taps` remains metadata for existing measured-table keys;
there is no interpolation in the raw-maximum gate.

## Changes from the audit

- Native run and series entry points validate output capacities, row counts,
  layout lengths, windows, and offset overflow before indexing or writing. This
  fixes an actual short-output overwrite in the flat native run entry point.
- Native output scratch grows only when needed and is reused. Python no longer
  allocates or fills a magnitude array that the public API never returns.
- Removed the unused shifted coarse template and its GPU allocations/uploads,
  doubled CPU coarse-template slots, runtime model/recovery machinery, unused
  helpers, and the obsolete gated shader entry point. Removed 70 unused gated
  SPIR-V/Metal artifacts; compacted refinement remains the production path.
- CPU/GPU threshold resolution shares one rule. Flat and hierarchical series
  share layout validation, output handling, and lifecycle behavior.
- GPU dispatch caches default to 512 MiB / 32 entries. Eviction releases
  buffers, Vulkan command buffers, and descriptor pools while retaining compiled
  pipelines. `clear_cache()` explicitly releases dispatch storage. Public
  `set_memory_limits(cache_bytes=..., series_bytes=...)` controls GPU budgets.
- GPU series gathers and FFTs run in batches with a default 64 MiB temporary
  budget. One block/dispatch may exceed its budget; returned output, stored
  input spectra, and compiled pipelines are not included. Smaller budgets trade
  throughput for memory. These are retention/working-set bounds, not a strict
  total-process memory ceiling.
- `tools/audit_selection.py` measures all calibrated bands, including bands
  without cost rows, on a chosen device and batch shape. It reports missing
  calibration/cost coverage, times candidates in alternating order, and can
  export repriced existing cost-covered bands via `--cost-output` for an
  explicit `MF_COST` override. Newly measured bands remain diagnostic until
  their accuracy is independently established; lookup alone is insufficient,
  as the low-ratio small-band defect in `tests/test_low_ratio_corner.py` shows. It does not alter shipped defaults or perform runtime autotuning.

Example: `python tools/audit_selection.py --n 4096 --data 8 --templates 32
--device gpu --json selection.json --cost-output measured-cost.txt`.

At n=4096, SNR=6, 8 data rows × 32 templates, the initial local audit found the
selected CPU band about 2× slower than the fastest calibrated candidate; the GPU
selection gap was about 10%. These measurements are workload-specific and noisy.
They justify collecting broader cost coverage, not replacing defaults with one
reference/batch measurement. The export supports evaluating that change explicitly.

## Validation and performance

New tests exercise malformed native buffers without writes outside their views,
resizing/reusing native scratch, missing calibration refusal, explicit settings
without any table access, reference changes after template ingestion, forced
GPU eviction, and one-block series batches. CLI tests cover the updated tuner
and cost export. Existing measured false-dismissal tests remain in the suite.

Interleaved comparisons used the committed native wrapper/hierarchical engine
and current code with the same underlying FFT kernels, inputs, and explicit
coarse threshold. Every benchmark checked output indices and values first.
At n=4096, 16×64 pairs, a CPU-affinity repeat measured current/baseline median
ratios of 1.006 (flat run), 0.982 (flat series), 1.015 (hierarchical run), and
0.989 (hierarchical series). GPU repeats measured 1.005, 0.995, 0.988, and 0.942,
respectively. Split-bin GPU medians varied from 0.91 to 1.06 across repeats, with
wide per-round scatter. There is no established material regression in these
workloads; small changes cannot be distinguished confidently from contention.
This is not a claim about every transform length or device.

A filter instance owns mutable buffers and is not intended for concurrent calls
from multiple threads. Use one instance per concurrent worker. Raw CPU results
reuse storage and must be copied if retained across calls. These ownership rules
also apply after scratch reuse and cache eviction.
