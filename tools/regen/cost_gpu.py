"""Measure the cost table for a GPU.

Cost is a property of the machine, and the shipped table is a CPU's. Using
it to choose a GPU configuration picks whatever is cheapest on a machine
with a completely different shape -- the CPU's coarse pass fits in L2 and
its refinement does not, while on a GPU both are bandwidth-and-occupancy
problems and the crossover sits somewhere else entirely.

The ACCURACY rows are untouched. They describe the algorithm -- which pairs a
coarse pass dismisses -- and that does not depend on the device.

What is measured is the same quantity the CPU table holds: cost RELATIVE to
a pivot configuration at the same transform length. A ratio, not a time, so
it stays meaningful across clocks and loads.

Two things the GPU does not use, and the table has to record anyway because
selection reads a fixed key: the oversample U is always 2 (the kernel
computes both coarse halves), and the taps K are unused (the interpolation
window is escalated rather than interpolated). Rows are therefore emitted
for every (U, K) the CPU table carries, sharing the measured value, so the
two tables stay interchangeable in shape.

Run:  python tools/regen/cost_gpu.py [--out cost-gfx11.txt]
"""
import argparse
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "tests"))
sys.path.insert(0, os.path.join(HERE, ".."))

import matchedfilter as mf
import hmf_tune as t
from test_api import inspiral_power, template_with_power, noise

SNRS = [5.0, 5.5, 6.0, 6.5]
MARGINS = [0.90, 0.94, 0.97, 1.00]
KS = [4, 8]
PAIRS = 4096


def measure(n, band, margin, snr, reps=8):
    """Seconds per run for one configuration, with the data already resident."""
    nd = 16
    nt = PAIRS // nd
    reference = inspiral_power(n)
    H = np.stack([template_with_power(n, inspiral_power(n, exponent=e))
                  for e in np.linspace(-7 / 3.0, -4 / 3.0, nt)])
    rng = np.random.default_rng(5)
    D = noise((nd, n), rng)
    # A few real signals, so the refinement path is exercised rather than
    # measuring a pure coarse pass that never escalates.
    for k in range(0, nd, 4):
        D[k] += (9.0 * H[(k * 7) % nt]
                 * np.exp(2j * np.pi * np.arange(n) * (300 + 11 * k) / n)
                 ).astype(np.complex64)

    f = mf.HierarchicalFilter(n, nd, nt, snr=snr, fd=1e-2, band=band,
                              oversample=2, taps=8, device="gpu")
    f.set_reference(reference)
    f.set_templates(H)
    f.set_coarse_margin(margin)
    f.set_data(D)
    f.run(binsize=n, threshold=snr)          # records the command buffer
    rate = f.refine_rate

    # Replay the recording: device work only. Timing run() instead put the
    # host's output marshalling in the number, and that is the same for every
    # configuration -- it swamped the differences being measured and made
    # adjacent margins come out non-monotonic.
    import ctypes
    from matchedfilter import _vkcompute as V
    ctx = f._gpu
    cmds = [b[1] for b in ctx._hier.values()] + [b[4] for b in ctx._batches.values()]
    arr = (V._vp * len(cmds))(*cmds)
    sub = V._SubmitInfo(4, None, 0, None, None, len(cmds), arr, 0, None)

    def go():
        ctx.vk.vkQueueSubmit(ctx.queue, 1, ctypes.byref(sub), None)
        ctx.vk.vkQueueWaitIdle(ctx.queue)

    for _ in range(3):
        go()
    best = float("inf")
    for _ in range(reps):
        t0 = time.perf_counter()
        go()
        best = min(best, time.perf_counter() - t0)
    ctx.destroy()
    return best, rate


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--sizes", default="1024,2048,4096,8192,16384")
    args = ap.parse_args(argv)

    dev = [d for d in mf.devices() if d.kind == "gpu" and not d.is_software]
    if not dev:
        print("no GPU", file=sys.stderr)
        return 1
    dev = dev[0]
    key = dev.arch[1] if len(dev.arch) > 1 else (dev.arch or ["gpu"])[0]
    out = args.out or os.path.join(os.path.dirname(mf.__file__),
                                   "cost-%s.txt" % key)

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        commit = "unknown"

    rows = []
    for n in [int(x) for x in args.sizes.split(",")]:
        bands = [b for b in t.bands_for(n) if b < n]
        pivot_band = max(bands)
        for snr in SNRS:
            pivot, _ = measure(n, pivot_band, 1.00, snr)
            for band in bands:
                p = np.asarray(inspiral_power(n), float)
                s = p[:band].sum()
                q = p[:band] / s if s > 0 else p[:band]
                f_in = float(s / p.sum())
                beff = float(1.0 / np.sum(q ** 2))
                for margin in MARGINS:
                    sec, rate = measure(n, band, margin, snr)
                    rel = sec / pivot
                    for K in KS:
                        rows.append((n, band, 2, K, snr, f_in, beff, margin, rel))
                    print("  n=%-6d band=%-5d snr=%.1f margin=%.2f  rel=%.4f "
                          "refine=%.3f" % (n, band, snr, margin, rel, rate),
                          flush=True)

    with open(out, "w") as fh:
        fh.write("# matchedfilter COST table -- RELATIVE cost per configuration\n#\n")
        fh.write("# device  %s\n" % dev.name)
        fh.write("# arch    %s  (also used for: %s)\n"
                 % (key, ", ".join(dev.arch)))
        fh.write("# commit  %s\n#\n" % commit)
        fh.write("# Measured on a GPU, with the data already resident: host\n"
                 "# transfers are not part of the configuration's cost and\n"
                 "# would swamp the differences between configurations.\n#\n")
        fh.write("# U is always 2 and K is unused on this backend -- the kernel\n"
                 "# computes both coarse halves and escalates the interpolation\n"
                 "# window rather than interpolating it -- so rows sharing an\n"
                 "# (n, band, snr, margin) share a measurement. They are emitted\n"
                 "# per (U, K) anyway so the table's key matches the CPU one.\n#\n")
        fh.write("# COST n band U K snr f beff margin rel\n")
        for r in rows:
            fh.write("COST %d %d %d %d %.2f %.4f %.1f %.3f %.4f\n" % r)
    print("wrote %s (%d rows)" % (out, len(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
