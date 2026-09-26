# GPU teaser throughput investigation

The initial new teaser reported 28.84 M pairs/s at fd=.01 (0.568 ms).
Do not interpret this as a demonstrated kernel regression. Its measurements
were not controlled for concurrent workloads on this shared machine.

Historical chart provenance matters:

- `b611cf2`: 96.4 M/s, 0.17 ms, private GPU command replay.
- `429d5c2`: 71.8 M/s, 0.23 ms, public API including result readback/assembly.
- Current teaser: public API, matched reference with random template phases;
  the historical bank varied power profiles against one common reference.

A controlled bank comparison using the same current code and model gate,
ndata=16, ntemplates=1024, n=4096, band=256, SNR=5.5, fd=.01, alternated
nine rounds with 150 calls per sample after 150 ms warmup per case:

| Bank | Median public API | Refined fraction |
|---|---:|---:|
| Historical heterogeneous, zero phase | 0.20355 ms | .047974 |
| Matched profile, random phases | 0.20204 ms | .047485 |

Automatic band selection reproduced this: 0.19981 / 0.20802 ms. Thus the
new bank itself did not create the reported threefold slowdown. These
measurements reach about 80 M/s without changing any kernel or gate.

Subsequent identical measurements became much slower and erratic, including
0.407 ms at fd=.01. A host process inspection found multiple concurrent
`pycbc_inspiral_fir` jobs, including `matchedfilter_gpu` benchmark outputs,
with each process consuming several CPU cores. Sustained warmup alone did
not remove this variability. GPU and CPU share memory bandwidth and power
on this machine. The amount attributable to GPU contention versus CPU load
has not been isolated, and original teaser-time load was not recorded.

The harness is preserved alongside this report. The teaser now warms for
0.5 s and measures >=50 ms blocks, retaining samples and warning about large
spread. This is not a substitute for a quiet measurement window. The initial
plot numbers were provisional until the quiet-window remeasurement below.

Optimization follow-up: at the same chosen band, refinement rises from
4.75% to 18.43% to 44.18% across fd=.01/.001/.0001. The cost table has no fd
or batch-shape axis. Compare candidate bands at each budget before treating
that band as optimal; never raise the model gate merely to recover speed.

Reproduce the band sweep with `PYTHONPATH=python python tools/audit_gpu_bands.py
--out /tmp/gpu-bands.json` (on this AMD host also preload the system
libstdc++ as required by the Vulkan driver). Run it without simultaneous
CPU/GPU performance tests.

## Quiet-window follow-up

The competing PyCBC jobs then exited; our correctness suite also completed
before measuring. With the combined current class/cache code, a nine-round
rotating/reversed candidate-band comparison measured:

| FDR | Automatic band 256 | Band 512 | Band 1024 |
|---|---:|---:|---:|
| .01 | .2015 ms | .1937 ms | .2631 ms |
| .001 | .4047 ms | .2267 ms | .2717 ms |
| .0001 | .7640 ms | .2928 ms | .2901 ms |

The current .01 default reaches **81.3 M pairs/s**. This does not reproduce
the apparent threefold regression. It does reveal a separate selection
limitation: band 512 is **1.8x / 2.6x faster** at the stricter budgets, with
its own unchanged model gate, by reducing the refinement population.
The .01 difference between 256 and 512 is small enough not to generalize.

The retained cost table has no FDR or batch-size axis. Replacing its global
ranking from this single profile would overfit a teaser; an appropriate
follow-up is budget/batch-aware cost calibration across representative
profiles. Users can already pin `band=512` while retaining model-based
accuracy. The regenerated teaser continues to show automatic defaults.
Full blocks and refinement rates are in `gpu-band-sweep.json`.

No filtering kernel was changed to recover the historical throughput.
Private command replay versus public API explains part of the difference
from the oldest 96.4 M/s result; contention and insufficiently characterized
measurement conditions explain why the new 28.8 M/s point is not reliable
regression evidence. The original run's exact interference is unmeasured.

The final sustained teaser run measured 82.01 / 41.43 / 21.30 M pairs/s
at the three budgets, with automatic band 256 throughout. GPU block ranges
were .193–.204 / .370–.405 / .748–.796 ms. All samples are in the teaser JSON.

Follow-up: the 8060S now has a [retuned cost table](../../measurements/gpu-cost-retune-2026-09-26.md)
with FDR and pair-count axes. The earlier teaser numbers above describe the
pre-retune configuration; the current teaser is remeasured with that table.
