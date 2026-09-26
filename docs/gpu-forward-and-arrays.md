# GPU forward FFT and shared array storage

`run_series()` now gathers/pads its blocks and computes the normalized
forward FFT with the library's GPU FFT code. The forward and inverse
transforms share `src/gpu/fft_transform.slang`: conjugate the input, run the
positive-sign transform, conjugate the output, and normalize by the length.
The CPU series path already uses the library's native forward FFT.
There are no NumPy FFT calls in either filter's execution path. Independent
NumPy FFTs remain in numerical tests and benchmark/reference programs.

Spectra stay in mapped GPU allocations between forward and correlation.
Hierarchical filtering extracts/converts the coarse band on the GPU too.
Vulkan reuses forward command recordings and submits forward plus correlation
with one completion wait. Metal encodes both into one command buffer.
The source segment is uploaded once per call unless it is already shared.
The series batch budget covers spectra, start offsets and result scratch;
it excludes the source upload and the final returned result. `clear_cache()`
releases the reusable series workspace along with dispatch buffers.
GPU sample addressing currently limits a source to UINT32_MAX samples;
offsets beyond the segment still produce zero-padded blocks, including
larger host-size offsets.

## Shared allocations and DLPack

```python
f = matchedfilter.MatchedFilter(4096, ndata=2, ntemplates=3, device="gpu")
data = f.empty_shared((2, 4096))       # complex64 by default
bank = f.empty_shared((3, 4096))
data[:] = data_spectra
bank[:] = template_spectra
f.set_data(data)
f.set_templates(bank)
peaks = f.run()
```

`empty_shared()` returns a NumPy array backed directly by this filter's
Vulkan host-visible/coherent or Metal shared-storage allocation. Contiguous
complex64 banks starting at the allocation's base bind directly, including
when passed through a host DLPack consumer. The ndarray/base/capsule ownership
chain keeps the allocation and context alive after cache eviction or deletion
of the filter. CPU filters return ordinary NumPy allocations.

Host DLPack-only producers are accepted consistently by indexed and bulk
setters, series data/layout arrays, and hierarchical reference power.
NumPy arrays also support the ordinary array and buffer protocols.

The limits are explicit:

- These arrays export **CPU DLPack**, not CUDA/ROCm device pointers. An
  arbitrary external accelerator allocation cannot be imported into Vulkan
  or Metal through this API. Such inputs raise without a hidden host transfer.
- The filter is synchronous. Finish producer writes before calling it;
  cross-library GPU stream synchronization is not implemented.
- Call the setter again after modifying a shared bank, so derived coarse
  templates and cached ordinary copies are refreshed. Shared banks alias
  caller storage; ordinary input banks retain their existing copy behavior.
- Dtype conversion, non-contiguous inputs, nonzero-offset bank slices and
  allocations owned by a different filter/context use the copying path.
- Returned peaks still use ordinary NumPy storage. This change removes the
  large input/intermediate copies, not the compact result readback.

Rebuild all production artifacts with
`python tools/build_spirv.py --slangc /path/to/slangc`. This includes forward,
packing and correlation SPIR-V and Metal sources; `tools/build_forward.py`
now delegates to the same complete build. The manifest lists forward/packing
artifacts and fingerprints shared shader dependencies, checked by shipping
tests. On Apple hosts the build also compiles all Metal sources into metallibs.

## Validation

Tests cover normalized forward values against an independent FFT, padding,
empty segments, changed data in reused storage, arbitrary window groups,
cache eviction, DLPack-only inputs, shared bank replacement, allocation
lifetimes and failed-call cleanup. Execution tests replace NumPy FFT functions
with exceptions. Available GPU sizes are tested, including the concurrent
wide-radix development sizes in the shared checkout.

Alternating old/new GPU-series timings on Radeon 8060S (median of 15 rounds,
three calls per round; warm kernels) gave:

| Length | Blocks | Templates | Previous host FFT | GPU forward | Speedup |
|---:|---:|---:|---:|---:|---:|
| 1024 | 64 | 32 | 0.828 ms | 0.180 ms | 4.59x |
| 4096 | 64 | 32 | 5.511 ms | 0.513 ms | 10.73x |
| 16384 | 32 | 32 | 9.410 ms | 1.108 ms | 8.50x |
| 4096 | 1 | 1 | 0.153 ms | 0.101 ms | 1.52x |

These are workload measurements on a shared development machine, not a
universal speedup claim. Initial two-submit code regressed the one-block case;
combining submissions removed that regression. Metal execution/performance
requires the macOS CI runner and is not locally measured on Linux.

Final Linux validation: **687 passed, 5 skipped** in the isolated commit
snapshot; **721 passed, 5 skipped** in the concurrent shared checkout.
The common-source extraction reproduced byte-identical existing correlation
SPIR-V at lengths 1024, 4096 and 16384, preserving those hot kernels.
