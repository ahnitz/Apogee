# Vulkan cached inputs: stale data across windows

Follow-up to `notes-for-mf-reporter.md`, September 26, 2026.

The synthetic single-input comparisons missed a host-side cache lifetime
bug. Each Vulkan dispatch key (window, threshold, shape, etc.) owns private
data and template buffers. The public filter clears its dirty flags after
one dispatch. Updating inputs through window A therefore left an already
cached window B holding the previous inputs. Returning to B with cleared
flags used those stale buffers. The same defect affected flat filtering and
the hierarchical coarse and full buffers.

Minimal reproducer: run windows A and B, replace data or templates, run A,
then run B. This produces wrong indices on the Radeon 8060S, before any
clustering. Thus clustering and floating-point conditioning do not explain
this particular failure. This is a plausible contributor to the PyCBC
report, not yet proof that it explains all of that report.

`_vkcompute.Context` now invalidates all resident copies of a changed input
and records freshness separately for each dispatch. It also records source
pointer, shape and strides to distinguish same-sized sub-ranges. A valid
unchanged resident input still skips the transfer. Freshness is recorded
only after successful writes.

Validation:

- Four host-buffer regressions and four real GPU regressions failed before
  the fix and passed after it, covering data/template changes and flat/hier
  dispatches. The GPU regressions check indices and complex values against
  float64; hierarchical thresholds are zero to isolate buffer correctness.
- A public API regression covers repeated template/data updates, window
  changes, and same-sized source sub-ranges against the CPU.
- The initial targeted run (upload cache, Vulkan, hierarchical matrix)
  passed all 87 tests on the 8060S.
- The full suite, including the public API regression, passed: **438 passed,
  3 skipped**, in 42.82 seconds on the same host.
- Replayed `/tmp/mfcap2/hier-00.npz` through `hier-11.npz` using flat CPU and
  GPU `run_series`, reusing plans across captures: all 842 detected peaks
  agreed in index, and values agreed at rtol=atol=1e-5. These are saved
  37-template captures, not the report's full 483-template search. The
  diagnostic script is `/tmp/mf_replay_cache.py`.

The complete original PyCBC search and its hierarchical false-dismissal
budget still need separate validation. No changes were made to the concurrent
CPU tuning edits or PyCBC integration file.

Environment: the sandbox hides `/dev/dri`. Outside it, Conda's libstdc++
initially prevented Mesa from loading. Tests ran with host device access and
`LD_PRELOAD=/usr/lib64/libstdc++.so.6`, using
`/home/ahnitz/miniconda3/bin/python -m pytest`.
