# Radeon 8060S cost retune, 2026-09-26

The old `cost-gfx11.txt` ranked bands using cost measurements at fd=.01.
At stricter budgets it chose a narrow band with too many pairs entering the
expensive full refinement. The new `cost-gfx1151.txt` is specific to the
Radeon 8060S architecture. Other gfx11 devices retain the older family table.

The GPU table has `# format cost-fd-pairs-v1` and rows of the form

```
COST n band U K snr fd pairs f beff relative_cost
```

CPU and older custom cost files retain their nine-field form. The explicit
format marker prevents an old ten-field gate-scale row from being mistaken
for a budget-aware row. Configuration selection uses the closest measured
SNR, log FDR, and log pair count, then interpolates relative cost in
(f, effective bandwidth) for the reference. Exact measured pair counts are
4096 and 16384. A plan supplies `ndata * ntemplates`; callers of
`choose_config` without a shape use 4096. Taps remain metadata on this GPU;
K=4 and K=8 have the same measured cost.
Cost keys are indexed when the table loads; at n=4096 a warm ranking takes
about 0.12 ms on this machine, outside the filtering loop.

Measurements use the model gate for **each band and budget**. They time warm
public `run()` calls, including GPU synchronization and result assembly.
Three FDRs (.01, .001, .0001), four SNRs (5, 5.5, 6, 6.5), five transform
lengths (1024 through 16384), two matched synthetic profiles (power-law
exponents -7/3 and -2), and two batch shapes (16x256 and 16x1024) were
swept. The real n=4096 PyCBC reference profile was added separately.
Timing order rotates and reverses. A concurrent PyCBC benchmark briefly
interrupted the sweep, so the calibration was paused; affected groups were
remeasured. The final 1056 raw band measurements have no block spread above
25%. Raw timing blocks, gates and refinement fractions are in
`gpu-cost-gfx1151-2026-09-26.json`.

The score compares the selected band's measured time with the old table at
each of 264 calibration workloads. The new table is faster by over 5% in
159, tied within 5% in 105, and slower by over 5% in none. Its median time
ratio is **0.690** (new/old). This is an in-sample check of the implementation
and measured choices, not independent evidence of generalization.

For n=4096, SNR 5.5 and 16x1024 pairs:

| Profile | FDR | Old band | New band | Old ms | New ms |
|---|---:|---:|---:|---:|---:|
| Inspiral -7/3 | .01 | 256 | 512 | .199 | .191 |
| Inspiral -7/3 | .001 | 256 | 512 | .372 | .230 |
| Inspiral -7/3 | .0001 | 256 | 1024 | .698 | .276 |
| Real PyCBC | .01 | 256 | 512 | .389 | .219 |
| Real PyCBC | .001 | 256 | 1024 | .896 | .268 |
| Real PyCBC | .0001 | 256 | 1024 | 1.328 | .318 |

The holdout uses exponent -5/3 and unseen shapes 8x512 and 16x512 at
n=4096, 8192 and 16384. Across all 12 holdout workloads, the new table is
faster than the old one by over 5%; median time ratio **0.494**. It does not
always choose the fastest tested band: worst measured regret is about 26%.
The table remains an approximate ranking, especially for unmeasured
profiles, shapes and hardware. Raw holdout timing and both selection scores
are retained beside this note. Reproduce with `tools/regen/cost_gpu.py`,
`tools/validate_gpu_cost_retune.py`, and `tools/score_gpu_cost_retune.py` on
an idle GPU.

Accuracy is unchanged for any fixed band: its gate is still computed from
the complete reference profile at the requested SNR and FDR. The cost file
only changes which eligible band gets chosen. Existing CPU/GPU component
accuracy tests continue to guard that separation.
