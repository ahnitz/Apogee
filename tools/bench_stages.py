#!/usr/bin/env python3
"""What the hierarchical stages actually cost, separately.

The GPU path is already three dispatches: coarse even, coarse odd (gated on
even), then the gated refine. The third launches ONE WORKGROUP PER PAIR and
most exit immediately after reading the gate -- so the question this answers
is what those wasted launches cost, which bounds what compaction plus an
indirect dispatch could recover.

Sweeps the threshold to move the refine rate across its range and fits
    time = fixed + marginal * refine_rate
The intercept is coarse plus wasted launches. The flat filter on the same
batch is the reference for "refine every pair with no gate at all".

Run:  python tools/bench_stages.py [n] [ndata] [ntmpl]
"""
import sys
import time

import numpy as np

sys.path.insert(0, "tests")
import matchedfilter as mf
from test_api import inspiral_power, template_with_power


def best(fn, reps=7):
    out = float("inf")
    for _ in range(reps):
        t0 = time.perf_counter()
        fn()
        out = min(out, time.perf_counter() - t0)
    return out


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 4096
    nd = int(sys.argv[2]) if len(sys.argv) > 2 else 16
    nt = int(sys.argv[3]) if len(sys.argv) > 3 else 256
    pairs = nd * nt

    dev = next((str(d) for d in mf.devices()
                if d.kind == "gpu" and not d.is_software), None)
    if not dev:
        print("no GPU")
        return 1
    print("device %s   n=%d  %d x %d = %d pairs" % (dev, n, nd, nt, pairs))

    p = np.asarray(inspiral_power(n), float)
    rng = np.random.default_rng(0)
    H = np.stack([template_with_power(n, p) for _ in range(nt)]).astype(np.complex64)
    D = (rng.standard_normal((nd, n))
         + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    # unit-variance filter output, so snr means what it says
    probe = np.fft.ifft(D[0] * np.conj(H[0])) * n
    D = (D / probe.real.std()).astype(np.complex64)

    flat = mf.MatchedFilter(n, nd, nt, device=dev)
    flat.set_data(D)
    flat.set_templates(H)
    flat.run(binsize=n, threshold=0.0)
    t_flat = best(lambda: flat.run(binsize=n, threshold=0.0))
    print("\nflat filter, every pair refined, no gate: %8.3f ms  (%.4f us/pair)"
          % (t_flat * 1e3, t_flat / pairs * 1e6))

    # Sweep the refine rate by injecting into k of the nd segments. Pure
    # noise dismisses everything at every snr, so a threshold sweep gives no
    # range at all -- the first version of this bench printed 0.00000 seven
    # times and would have fitted a line through one point.
    print("\n%-6s %-12s %-12s %-14s" % ("inject", "refine_rate", "total ms", "us/pair"))
    rows = []
    snr = 5.5
    for k in (0, 1, 2, 4, 8, 16):
        Dk = D.copy()
        for j in range(min(k, nd)):
            lag = 100 + 7 * j
            ph = np.exp(-2j * np.pi * np.arange(n) / n).astype(np.complex64)
            Dk[j] += (H[0] * (ph ** lag) * np.float32(20.0)).astype(np.complex64)
        try:
            hf = mf.HierarchicalFilter(n, nd, nt, snr=snr, fd=1e-2, device=dev)
            hf.set_reference(p)
            hf.set_templates(H)
            hf.set_data(Dk)
            hf.run(binsize=n, threshold=snr)
            t = best(lambda: hf.run(binsize=n, threshold=snr))
            r = hf.refine_rate
        except Exception as e:
            print("%-6d  %s" % (k, str(e)[:60]))
            continue
        rows.append((r, t))
        print("%-6d %-12.5f %-12.3f %-14.4f" % (k, r, t * 1e3, t / pairs * 1e6))

    if len(rows) >= 2:
        r = np.array([x[0] for x in rows])
        t = np.array([x[1] for x in rows])
        if np.ptp(r) > 1e-6:
            marginal, fixed = np.polyfit(r, t, 1)
        else:
            marginal, fixed = float("nan"), t.mean()
        print("\n  time = fixed + marginal * refine_rate")
        print("    fixed    %8.3f ms   coarse passes PLUS the wasted launches" % (fixed * 1e3))
        print("    marginal %8.3f ms   refining every pair would add this" % (marginal * 1e3))
        print("    flat     %8.3f ms   refining every pair with no gate" % (t_flat * 1e3))
        if marginal == marginal and t_flat > 0:
            print("\n  fixed cost as a share of the flat filter: %.1f%%"
                  % (100 * fixed / t_flat))
            print("  -> that share is the ceiling on what compaction can save,")
            print("     minus whatever the coarse transforms genuinely cost.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
