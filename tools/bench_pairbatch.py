#!/usr/bin/env python3
"""Interleave forced balanced/pair-batched plans, checking complex results."""
import argparse
import os
import statistics
import time

import numpy as np
import matchedfilter as mf


def measure(n, nd, nt, rounds=7, repeats=40, fraction=1., ingest=False):
    rng = np.random.default_rng(n + nd + nt)
    def noise(shape):
        return (rng.normal(size=shape) + 1j*rng.normal(size=shape)).astype(np.complex64)
    data, templates = noise((nd, n)), noise((nt, n))
    plans = []
    previous = os.environ.get("MF_PBMAX")
    try:
        for cutoff in (128, 1024, None):
            if cutoff is None:
                os.environ.pop("MF_PBMAX", None)
            else:
                os.environ["MF_PBMAX"] = str(cutoff)
            f = mf.MatchedFilter(n, nd, nt)
            f.set_templates(templates)
            f.set_data(data)
            plans.append(f)
    finally:
        if previous is None:
            os.environ.pop("MF_PBMAX", None)
        else:
            os.environ["MF_PBMAX"] = previous
    lo = int(n*(1-fraction)/2)
    kw = dict(binsize=n, window=(lo,n-lo), raw=True)
    out = [f.run(**kw) for f in plans]
    for got in out[1:]:
        np.testing.assert_array_equal(out[0][0], got[0])
        np.testing.assert_allclose(out[0][1], got[1], rtol=1e-5, atol=1e-4)
    times = [[], [], []]
    for r in range(rounds):
        for i in ((0, 1, 2) if r % 2 == 0 else (2, 1, 0)):
            t0 = time.perf_counter()
            for _ in range(repeats):
                if ingest:
                    plans[i].set_data(data)
                    plans[i].set_templates(templates)
                plans[i].run(**kw)
            times[i].append((time.perf_counter()-t0)/repeats)
    ratios = [a/b for a, b in zip(times[0], times[2])]
    return (*[statistics.median(t) for t in times],
            statistics.median(ratios), sum(r > 1 for r in ratios))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rounds", type=int, default=7)
    p.add_argument("--repeats", type=int, default=40)
    p.add_argument("--sizes", type=int, nargs="+", default=[256, 512, 1024])
    p.add_argument("--window-fraction", type=float, default=1.)
    p.add_argument("--include-ingest", action="store_true")
    args = p.parse_args()
    print("backend", mf.backend(), flush=True)
    print("n nd nt balanced_us pair_us auto_us auto_speedup wins", flush=True)
    for n in args.sizes:
        for nd, nt in ((1, 1), (32, 1), (1, 8), (8, 8), (1, 16), (8, 16),
                       (1, 24), (8, 24), (1, 32), (8, 37), (8, 64)):
            a, b, c, ratio, wins = measure(n, nd, nt, args.rounds, args.repeats,
                                          args.window_fraction, args.include_ingest)
            print(n, nd, nt, f"{a*1e6:.2f}", f"{b*1e6:.2f}",
                  f"{c*1e6:.2f}", f"{ratio:.3f}", f"{wins}/{args.rounds}", flush=True)


if __name__ == "__main__":
    main()
