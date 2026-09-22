#!/usr/bin/env python3
"""Tune the whole first-stage configuration by running the real filter.

Not a model.  An earlier version of this re-derived the statistic in numpy and
Monte-Carloed that, and it was wrong in the way re-derivations are wrong: it
reported a measured false dismissal of 0.0 for band 256 at U=1 -- a
configuration the captures show triggering 60% of the time, and which misses
244 of 842 triggers.  Anything that does not run the code cannot be trusted to
tune the code.

So every candidate here is built as an actual HierarchicalFilter with that
(band, oversample, taps), handed the same reference and bank, and run against
injections.  The ungated MatchedFilter on the same data is the truth, exactly
as tools/hier_bench.py does it, and a dismissal is a peak the flat filter
reports that the hierarchical one does not.  Cost is wall time of the same
call, not a formula.

The consequence worth having: after any change to the kernel or the gate, this
can be re-run and will say whether the compiled choices still hold.

    python tools/hmf_tune.py --n 4096 --snr 5.0 --fd 1e-3 --trials 4000
"""
import argparse
import sys
import time

import numpy as np

sys.path.insert(0, "tests")
from test_api import (inspiral_power, template_with_power, noise)  # noqa: E402
import matchedfilter as mf                                    # noqa: E402


def measure(n, band, U, K, snr, trials, seed=13, nt=1):
    """Measured (dismissal, seconds) for one configuration, through the API.

    Injects a signal at a known lag into noise, runs the ungated filter and
    the hierarchical one on the same spectrum, and counts the peaks the first
    reports that the second does not.  Same recipe as
    test_omission_rate_meets_the_budget, which is the suite's existing
    statement of the guarantee -- so the tuner and the test cannot disagree
    about what a dismissal is.
    """
    rng = np.random.default_rng(seed)
    power = inspiral_power(n)
    H = template_with_power(n, power)
    flat = mf.MatchedFilter(n, ndata=1, ntemplates=1)
    hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=1, snr=snr, fd=1e-3,
                               band=band, oversample=U, taps=K)
    hf.set_reference(power)
    flat.set_templates(H[None, :])
    hf.set_templates(H[None, :])

    detected = omitted = 0
    sec = 0.0
    ph = np.exp(2j * np.pi * np.arange(n) / n)
    for i in range(trials):
        lag = (37 * i) % n
        D = noise((1, n), rng)
        D[0] += (snr * H * ph ** lag).astype(np.complex64)
        flat.set_data(D)
        hf.set_data(D)
        a = flat.run(binsize=n, threshold=snr)
        t0 = time.perf_counter()
        b = hf.run(binsize=n, threshold=snr)
        sec += time.perf_counter() - t0
        if a["index"][0, 0, 0] >= 0:
            detected += 1
            omitted += b["index"][0, 0, 0] < 0
    return (omitted / detected if detected else 1.0), detected, sec / max(trials, 1)


def tune(n, snr, fd, trials=1500, seed=13, bands=None, verbose=True):
    if bands is None:
        bands = [b for b in (256, 512, 1024, 2048, 4096) if b <= n // 2]
    rows = []
    for band in bands:
        for U in (1, 2):
            for K in (4, 8):
                try:
                    dm, det, sec = measure(n, band, U, K, snr, trials, seed)
                except Exception as e:                       # unsupported combo
                    if verbose:
                        print("  band %-5d U=%d K=%-3d  unavailable (%s)"
                              % (band, U, K, e))
                    continue
                ok = dm <= fd
                rows.append(dict(band=band, U=U, K=K, dismissal=dm,
                                 detected=det, sec=sec, ok=ok))
                if verbose:
                    print("  band %-5d U=%d K=%-3d  dismissed %.3e of %d  "
                          "%7.3f ms  %s" % (band, U, K, dm, det, sec * 1e3,
                                            "OK" if ok else "REJECT"))
    live = [r for r in rows if r["ok"]]
    return (min(live, key=lambda r: r["sec"]) if live else None), rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--snr", type=float, default=5.0)
    ap.add_argument("--fd", type=float, default=1e-3)
    ap.add_argument("--trials", type=int, default=1500)
    a = ap.parse_args()
    print("n=%d snr=%.1f fd=%.0e -- every row is the real filter, not a model\n"
          % (a.n, a.snr, a.fd))
    best, _ = tune(a.n, a.snr, a.fd, trials=a.trials)
    print("\nPICK: %s" % (best if best else "nothing met the target"))


if __name__ == "__main__":
    main()
