#!/usr/bin/env python3
"""Check the shipped coarse-threshold table against measurement, cell by cell.

The table says, for a given (n, f, ratio, snr, fd), the highest coarse
threshold whose false dismissal still meets `fd`.  Nothing checked that
claim after the rows were written, and it does not hold uniformly: the rows
are optimistic at low `ratio` and the error grows as the ratio falls.

    n=4096, snr 5.0, fd 1e-3, 6000 injections a bisection step

    band   f       ratio   measured safe   table    table is
     128   0.6970   1.24       2.8956      3.3341   15.1% HIGH
     256   0.8832   1.66       3.3843      3.5307    4.3% high
     512   0.9584   2.83       3.8774      4.0354    4.1% high
    1024   0.9882   5.33       4.3502      4.2423    2.5% low

A threshold that is too high dismisses signals, so "high" is the unsafe
direction.  At ratio 5 and above the table is fine.  Below it the table is
a few percent optimistic, which the configurations survive because they
have slack, and at ratio 1.24 the error reaches 15% and breaks through --
band 128 there dismisses 2.9e-2 against a 1e-3 budget, which is why bands
64 and 128 are supported but not selectable.  See
tests/test_low_ratio_corner.py and docs/tooling-cleanup.md.

This measures the same quantity the table claims, in the same units, the
way a caller experiences it: inject at the design SNR into noise, filter
with the flat filter and the hierarchical one, and count the peaks the flat
filter reports that the hierarchical one does not.

It does NOT reuse hmf_tune.measure_tc, nor
tools/regen/threshold_lowratio.py, and that duplication is DELIBERATE.
Those are the producers; this is the check. A check sharing the producer's
setup cannot see a fault in it, which is exactly how the original error
survived -- the rows and their only validation came from one code path.
Do not factor the three together.

    python tools/audit_threshold.py                     # the four cells above
    python tools/audit_threshold.py --band 128 --trials 20000
    python tools/audit_threshold.py --n 8192 --snr 5.5 --fd 1e-2

TRIALS. `fd` is a rate, so the trial count sets what can be resolved: at
`trials` injections a budget of `fd` expects `trials * fd` events, and
fewer than a handful cannot separate a pass from a draw. The default 6000
expects 6 at 1e-3, which is enough to place the threshold to a few percent
and not enough to certify a single cell -- the shipped rows were measured
at that count and this is the tool that found them wrong.
"""
import argparse
import sys
import time

import numpy as np

sys.path.insert(0, "tests")
import matchedfilter as mf                                   # noqa: E402
from test_api import inspiral_power, template_with_power, noise  # noqa: E402


class Cell:
    """One (n, reference, band, snr, fd) cell, ready to measure at any
    threshold.

    The bank and both plans depend only on the cell, not on the threshold
    under test, so they are built once here rather than inside the
    bisection -- which calls measure() nine times and was paying for nine
    banks, nine flat plans and nine hierarchical plans to vary one float.

    Holds only what it needs, so nothing of the caller's scope stays alive
    for the length of a sweep.
    """

    def __init__(self, n, power, band, snr, fd, nt=16, nb=64, seed=101):
        self.n, self.snr, self.fd = n, snr, fd
        self.nt, self.nb, self.seed = nt, nb, seed
        self.H = np.stack([template_with_power(n, power) for _ in range(nt)])
        self.flat = mf.MatchedFilter(n, nb, nt)
        self.flat.set_templates(self.H)
        self.hier = mf.HierarchicalFilter(n, nb, nt, snr=snr, fd=fd,
                                          band=band, taps=8)
        self.hier.set_reference(power)
        self.hier.set_templates(self.H)
        self.ph = np.exp(2j * np.pi * np.arange(n) / n)

    def measure(self, threshold, trials):
        """(detected, omitted) at one coarse threshold."""
        n, nb, nt, snr = self.n, self.nb, self.nt, self.snr
        self.hier.set_coarse_threshold(threshold)
        rng = np.random.default_rng(self.seed)
        detected = omitted = 0
        for _ in range((trials + nb - 1) // nb):
            D = noise((nb, n), rng)
            which = rng.integers(0, nt, nb)
            for b in range(nb):
                lag = int(rng.integers(0, n))
                D[b] += (snr * self.H[which[b]]
                         * self.ph ** lag).astype(np.complex64)
            self.flat.set_data(D)
            self.hier.set_data(D)
            a = self.flat.run(binsize=n, threshold=snr)
            c = self.hier.run(binsize=n, threshold=snr)
            for b in range(nb):
                t = which[b]
                if a["index"][b, t, 0] >= 0:
                    detected += 1
                    omitted += int(c["index"][b, t, 0] < 0)
        return detected, omitted


def highest_safe(n, power, band, snr, fd, trials, steps=9, verbose=False):
    """Bisect for the largest coarse threshold whose dismissal meets `fd`."""
    table = mf.choose_threshold(power, n, snr, fd, band)
    cell = Cell(n, power, band, snr, fd)
    lo, hi = 2.0, table * 1.15
    for _ in range(steps):
        mid = 0.5 * (lo + hi)
        det, om = cell.measure(mid, trials)
        rate = om / max(det, 1)
        ok = det > 0 and rate <= fd
        if verbose:
            print("     thr %.4f  %4d of %5d = %.2e  %s"
                  % (mid, om, det, rate, "safe" if ok else "OVER"))
        if ok:
            lo = mid
        else:
            hi = mid
    return lo, table


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--snr", type=float, default=5.0)
    ap.add_argument("--fd", type=float, default=1e-3)
    ap.add_argument("--band", type=int, nargs="*",
                    default=[128, 256, 512, 1024])
    ap.add_argument("--knee", type=float, default=0.0150,
                    help="reference knee; moves where each band lands in ratio")
    ap.add_argument("--trials", type=int, default=6000,
                    help="injections a bisection step; %d*fd events expected"
                         % 6000)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    power = inspiral_power(a.n, knee_frac=a.knee)
    expect = a.trials * a.fd
    print("n=%d snr=%.1f fd=%.0e  %d injections a step, %.1f events expected "
          "at the budget%s" % (a.n, a.snr, a.fd, a.trials, expect,
                               "" if expect >= 5 else "  -- TOO FEW TO SEPARATE"))
    print("%6s %8s %8s %7s %10s %10s  %s"
          % ("band", "f", "B_eff", "ratio", "measured", "table", "table is"))
    worst = None
    for band in a.band:
        f, be = mf._band_features(power, band)
        if be <= 0:
            continue
        t0 = time.time()
        try:
            safe, table = highest_safe(a.n, power, band, a.snr, a.fd,
                                       a.trials, verbose=a.verbose)
        except ValueError as e:
            print("%6d %8.4f %8.1f %7.2f  refused: %s"
                  % (band, f, be, band / be, str(e)[:44]))
            continue
        err = 100.0 * (table / safe - 1.0)
        print("%6d %8.4f %8.1f %7.2f %10.4f %10.4f  %5.1f%% %s   [%.0fs]"
              % (band, f, be, band / be, safe, table, abs(err),
                 "HIGH" if err > 0 else "low ", time.time() - t0))
        if worst is None or err > worst[0]:
            worst = (err, band)
    if worst and worst[0] > 10.0:
        print("\nband %d is %.0f%% optimistic. A threshold above the safe "
              "value dismisses signals, so this cell does not meet the "
              "budget it advertises." % (worst[1], worst[0]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
