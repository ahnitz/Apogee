# Further optimization audit

Reviewed the shared checkout after 84547b8, including concurrent GPU-extension
work, on 2026-09-26. These are opportunities, not implemented speedups. No
filtering code changed in this audit. Historical roadmap sections describing
an odd coarse pass or tap interpolation do not describe the current execution.

## Recommended order

1. **Pack CPU results directly into the requested output format.** `_core.c`
   currently copies native `ap_peak` scratch into index/value arrays, and the
   Python wrapper copies those into the structured result. Add a structured
   output destination to the native wrapper so normal calls skip the intermediate
   arrays, retaining the existing raw contract and native ABI. Avoid allocating
   an unused structured buffer for raw-only callers. Greatest benefit: many
   bins or large pair counts. Check dtype, output lifetime, counts and empty
   detections as well as indices/complex values.

   An interleaved CPU probe used n=1024, 8 data rows, 32 templates, random
   complex64 spectra, threshold zero, 20 calls per timing and nine alternating
   rounds after warmup. Median structured/raw times: 0.168/0.166 ms for
   binsize=1024; 4.575/3.159 ms for binsize=1. The existing raw mode was ~31%
   faster in the output-heavy case. This is evidence of output overhead, not
   a forecast that a new structured implementation will recover all of it.
   The shared machine was not isolated from other work.

2. **Avoid repeating GPU transforms for large bin counts.** Both backends split
   outputs exceeding 2048 bins into recursive whole-filter calls. At n=16384,
   binsize=1, a full window requires eight pieces. Hierarchical pieces repeat
   coarse transforms/compaction, and surviving pairs repeat refinement FFTs;
   flat pieces also repeat their transforms. Consider a separate many-bin path
   that materializes a transform once and reduces output bins in tiles. Keep
   the fused small-output path. Preserve each piece's coarse-window decision:
   substituting a single whole-window maximum would change which peaks survive.
   Materialization adds traffic, so determine its crossover empirically.

3. **Separate GPU input residency from dispatch recordings.** Window, bin size,
   final threshold and coarse threshold are in cache keys; each entry owns a
   full input/template buffer set. The same spectra can therefore be stored and
   uploaded repeatedly across variants. Share input storage by shape and input
   generation while keeping output storage and command parameters separate.
   Then replace clear-all eviction with selective eviction under the existing
   byte/entry budgets. This targets changing-window workloads and memory use;
   steady single-key calls may see little benefit. Preserve dirty-generation,
   subrange, recording-lifetime and eviction tests on both Vulkan and Metal.

4. **Reduce CPU work and serialization in GPU series execution.** The path
   allocates gather-index/mask/block arrays, runs NumPy forward FFTs on CPU,
   casts spectra, dispatches and waits for each batch. First try reusable gather
   storage, grouping layouts once, avoiding provably redundant output clearing,
   and a forward-FFT backend that avoids precision-conversion temporaries on
   supported NumPy versions. Larger project: device-side gather/forward FFT and
   a bounded double-buffered pipeline. Replacing queue-idle with a fence alone
   will not create overlap: multiple submissions and independent buffer slots
   are needed. The 8060S shares system memory, so do not assume discrete-GPU
   PCIe transfer savings. Include tail padding and ragged windows in validation.

5. **Reduce CPU packing for sparse or misaligned template groups.**
   `run_pairs_pb` clears both entire temporary template buffers before filling
   selected lanes. Fully occupied groups need no clearing; partial groups need
   only unused lanes initialized. Contiguous aligned survivor groups could
   use the prepacked bank directly. Measure ragged counts and sparse/dense
   survivor populations separately. The existing aligned dense path already
   bypasses this packing, so it should stay untouched.

6. **Improve GPU compaction for dense survivors and many output bins.**
   `compactPairs` performs one global atomic increment per survivor and has one
   thread clear every output bin of each dismissed pair. A subgroup prefix scan
   with one atomic per subgroup could reduce contention; cooperative clearing
   could improve coalescing for many bins. These are lower-priority candidates:
   sparse single-bin workloads may lose to extra control/reduction overhead.
   Check exact survivor counts, odd pair counts, subgroup widths, and both
   Vulkan and Metal before considering a default change.

## Selection and calibration

Cost selection remains a separate opportunity: device/batch-shape measurements
can change which already-validated band wins. Use `tools/audit_selection.py` and
its explicit cost-file output to measure that. Do not add small-band candidates
merely because their noise timings look good: the known low-ratio calibration
corner needs accuracy work, and tighter gates are not a valid optimization.
No calibration fallback or runtime threshold guessing is proposed here.

Start with direct result packing and repeated-transform elimination. They have
concrete avoidable work in the current source, clear workload boundaries, and
can be evaluated without changing calibration or coarse-gate semantics.
