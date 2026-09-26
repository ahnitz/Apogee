#!/usr/bin/env python3
"""Does the selected configuration actually deliver the requested FDR?

This is the acceptance test for the selection rule, and it asks the only
question that matters: ask for a false-dismissal budget, take whatever
configuration selection returns, and MEASURE what that configuration
really dismisses on the reference it was chosen for.

Deliberately not a test of the table. The table can be right cell by cell
and the rule still wrong, which is exactly what happened before.
"""
import sys, argparse
import numpy as np
import multiprocessing as mp
sys.path.insert(0, 'tools')
import hmf_tune as t
import matchedfilter as mf


def references(n):
    """References spanning what real callers produce."""
    k = np.arange(1, n // 2)
    out = []
    for name, knee, slope in (("inspiral", 0.0150, -7 / 3.0),
                              ("shallow",  0.0300, -5 / 3.0),
                              ("steep",    0.0080, -3.0)):
        p = np.zeros(n)
        p[1:n // 2] = k ** slope / ((knee * n / k) ** 4 + 1.0)
        out.append((name, (p / p.sum()).astype(np.float32)))
    return out


def one(job):
    n, snr, fd, name, p, trials = job
    try:
        cfg = mf.choose_config(p, n, snr, fd)
    except Exception as e:
        return dict(n=n, snr=snr, fd=fd, ref=name, cfg=None, err=str(e))
    if cfg is None:
        return dict(n=n, snr=snr, fd=fd, ref=name, cfg=None, err="no config")
    # No margin. choose_config used to return one and this passed it back
    # in, which measured a configuration the library never runs: the margin
    # is an axis of the measured grid, and what the filter is actually run
    # at is the threshold from threshold.txt. Measuring the chosen config
    # means measuring it as the library will build it.
    band, K = cfg
    dm, det, _sec = t.measure(n, band, 1, K, snr, trials, power=p)
    f, be = mf._band_features(p, band)
    return dict(n=n, snr=snr, fd=fd, ref=name, cfg=cfg, f=f, beff=be,
                dismissal=dm, detected=det)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ns", type=int, nargs="+", default=[1024, 2048, 4096, 8192])
    ap.add_argument("--trials", type=int, default=20000)
    ap.add_argument("--jobs", type=int, default=12)
    a = ap.parse_args()

    jobs = []
    for n in a.ns:
        for name, p in references(n):
            for snr in (5.0, 6.0):
                for fd in (1e-2, 1e-3):
                    jobs.append((n, snr, fd, name, p, a.trials))
    with mp.Pool(a.jobs) as pool:
        rows = pool.map(one, jobs)

    print("%-7s %-5s %-7s %-9s %-20s %-7s %-11s %s"
          % ("n", "snr", "fd", "ref", "chosen", "B_eff", "measured", "vs budget"))
    over = tot = 0
    for r in sorted(rows, key=lambda r: (r["n"], r["ref"], r["snr"], r["fd"])):
        if r.get("cfg") is None:
            print("%-7d %-5.1f %-7.0e %-9s %s" % (r["n"], r["snr"], r["fd"],
                                                  r["ref"], r.get("err")))
            continue
        tot += 1
        ratio = r["dismissal"] / r["fd"]
        if ratio > 1.0:
            over += 1
        print("%-7d %-5.1f %-7.0e %-9s %-20s %-7.0f %-11.2e %s%.2fx"
              % (r["n"], r["snr"], r["fd"], r["ref"],
                 "band %d / K %d" % r["cfg"], r["beff"], r["dismissal"],
                 "  " if ratio <= 1 else "OVER ", ratio))
    print("\n%d of %d over budget" % (over, tot))


if __name__ == "__main__":
    main()
