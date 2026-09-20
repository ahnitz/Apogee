#!/usr/bin/env python3
"""Plot the batched matrix: bat_{avx512,avx2}_{quiet,load}.csv -> bench_batch.png

Shows speedup over each baseline rather than raw microseconds, because the
absolute numbers move by 2x with machine load and the ratios do not.
"""
import csv, sys
from collections import defaultdict
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REGIMES = [("avx512", "quiet"), ("avx512", "load"), ("avx2", "quiet"), ("avx2", "load")]

def load(isa, cond):
    rows = defaultdict(dict)
    try:
        with open(f"bat_{isa}_{cond}.csv") as f:
            for r in csv.DictReader(f):
                n, b = int(r["N"]), int(r["B"])
                best = min(float(r["peakfft"]), float(r["peakfft_thr"]))
                rows[b][n] = {k: float(r[k]) / best for k in ("mkl", "sysfftw", "amdfftw")}
    except FileNotFoundError:
        return None
    return rows

fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharex=True, sharey=True)
COLORS = {"mkl": "#1f77b4", "sysfftw": "#2ca02c", "amdfftw": "#d62728"}
LABELS = {"mkl": "MKL", "sysfftw": "FFTW", "amdfftw": "amd-fftw"}

for ax, (isa, cond) in zip(axes.ravel(), REGIMES):
    rows = load(isa, cond)
    ax.set_title(f"{isa} / {cond}")
    ax.axhline(1.0, color="k", lw=1.2, ls="--")
    ax.set_yscale("log", base=2)
    ax.grid(alpha=0.3, which="both")
    if not rows:
        ax.text(0.5, 0.5, "no data", ha="center", transform=ax.transAxes)
        continue
    batches = sorted(rows)
    for lib in ("mkl", "sysfftw", "amdfftw"):
        for i, b in enumerate(batches):
            ns = sorted(rows[b])
            ys = [rows[b][n][lib] for n in ns]
            ax.plot([n.bit_length() - 1 for n in ns], ys, color=COLORS[lib],
                    alpha=0.35 + 0.65 * i / max(len(batches) - 1, 1),
                    marker="o", ms=3, lw=1.3,
                    label=f"{LABELS[lib]} (B={b})" if True else None)
    ax.set_xlabel("log2 N")
    ax.set_ylabel("baseline time / peakfft time")

h, l = axes[0][0].get_legend_handles_labels()
fig.legend(h, l, loc="lower center", ncol=6, fontsize=7, frameon=False)
fig.suptitle("peakfft batched top-K vs full-FFT baselines — above 1.0 means peakfft wins\n"
             "(K=8, one core of a Zen 5 Ryzen AI MAX+ 395, batch sizes 16/32/64/128)")
fig.tight_layout(rect=(0, 0.07, 1, 1))
fig.savefig("bench_batch.png", dpi=130)
print("wrote bench_batch.png")
