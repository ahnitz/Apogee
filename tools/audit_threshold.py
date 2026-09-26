#!/usr/bin/env python3
"""Independently check the profile-model coarse gate against filter injections.

Bisection estimates the largest empirical gate meeting the requested budget.
This implementation is deliberately independent of hmf_tune.measure and the
model sampler. Rare budgets require enough detected injections: 100 events
below the gate give roughly 10% relative counting uncertainty.

    python tools/audit_threshold.py --band 1024 --trials 100000
    python tools/audit_threshold.py --n 1024 --band 256 --fd .0001 --trials 1500000
"""
import argparse
import os
import statistics
import sys
import time

import numpy as np

# Resolved against THIS file, not the working directory. A cwd-relative
# entry only works when the tool is run from the checkout root, which is
# the same defect already fixed once in tests/test_low_ratio_corner.py.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(os.path.dirname(_HERE), "tests"), _HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import matchedfilter as mf                                   # noqa: E402
import hmf_tune as ht                                        # noqa: E402
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


def repeatability(n, band, f_target, ratio, snr, fd, trials, steps, seeds):
    """Spread of ONE cell measured repeatedly, which is the floor every
    other spread has to clear.

    Measured before this existed, nothing quoted here had a noise floor
    against it. At n=4096 band 512 fd=1e-2 with 3000 trials a step, eight
    seeds give sd 1.0-1.3% and a full range of 2.5-3.8%. That makes the
    19.9% band spread at f=0.60 about twenty sigma and real, and the 3.1%
    at f=0.995 indistinguishable from re-running the same cell.
    """
    # The reference does not depend on the seed, and make_ref runs a
    # 60-step bisection of its own to hit the target bandwidth.
    power = ht.make_ref(n, band, f_target, band / ratio)
    vals = []
    for seed in seeds:
        cell = Cell(n, power, band, snr, fd, seed=seed)
        lo, hi = 2.0, 4.6
        for _ in range(steps):
            mid = 0.5 * (lo + hi)
            det, om = cell.measure(mid, trials)
            if det > 0 and om / det <= fd:
                lo = mid
            else:
                hi = mid
        vals.append(lo)
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return vals, mean, sd, 100.0 * (max(vals) / min(vals) - 1.0)


def coverage(paths):
    """Describe measured cost features; these are not accuracy limits."""
    q = []
    for n in (2048, 4096, 8192, 16384):
        for e in (-7 / 3.0, -2.0, -5 / 3.0):
            for knee in (0.0150, 0.05, 0.002):
                power = inspiral_power(n, exponent=e, knee_frac=knee)
                for band in (128, 256, 512, 1024, 2048):
                    if band >= n:
                        continue
                    f, be = mf._band_features(power, band)
                    if be > 0:
                        q.append((f, be, band / be))
    lim = {"f": (min(x[0] for x in q), max(x[0] for x in q)),
           "B_eff": (min(x[1] for x in q), max(x[1] for x in q)),
           "ratio": (min(x[2] for x in q), max(x[2] for x in q))}
    print("operating range over %d (n, band, reference) combinations:" % len(q))
    for k in ("f", "B_eff", "ratio"):
        print("   %-6s %10.3f to %10.3f" % (k, lim[k][0], lim[k][1]))
    print()
    for path, tag, cols in paths:
        try:
            rows = [l.split() for l in open(path) if l.startswith(tag)]
        except OSError:
            print("   %-46s  unreadable" % path)
            continue
        if not rows:
            print("   %-46s  no %s rows" % (path, tag))
            continue
        print("   %s" % path)
        for name, idx in cols:
            v = [float(r[idx]) for r in rows if len(r) > idx]
            lo, hi = min(v), max(v)
            want = lim[name]
            gap = lo > want[0] * 1.001 or hi < want[1] * 0.999
            print("      %-6s %10.3f to %10.3f   %s"
                  % (name, lo, hi,
                     "GAP: operating range is %.3f to %.3f"
                     % want if gap else "covers"))


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
    ap.add_argument("--coverage", action="store_true",
                    help="report each table's grid against the range real "
                         "references query, and exit")
    ap.add_argument("--repeat", type=int, default=0, metavar="SEEDS",
                    help="measure ONE cell this many times and report the "
                         "spread: the noise floor any other spread must "
                         "clear. Uses --band[0], --f-target and --ratio.")
    ap.add_argument("--f-target", type=float, default=0.60)
    ap.add_argument("--ratio", type=float, default=1.2)
    a = ap.parse_args()

    if a.repeat:
        seeds = [11, 23, 37, 53, 71, 97, 131, 167, 199, 233][:a.repeat]
        band = a.band[0]
        vals, mean, sd, rng = repeatability(a.n, band, a.f_target, a.ratio,
                                            a.snr, a.fd, a.trials, 7, seeds)
        print("n=%d band=%d f=%.3f ratio=%.2f snr=%.1f fd=%.0e, %d trials/step"
              % (a.n, band, a.f_target, a.ratio, a.snr, a.fd, a.trials))
        print("   %s" % " ".join("%.3f" % v for v in vals))
        print("   mean %.4f  sd %.4f (%.1f%%)  full range %.1f%% over %d seeds"
              % (mean, sd, 100 * sd / mean, rng, len(seeds)))
        print("\nA spread below about %.0f%% is not distinguishable from "
              "re-running this cell." % rng)
        return 0

    if a.coverage:
        coverage([
            ("python/matchedfilter/cost.txt", "COST",
             [("f", 6), ("B_eff", 7)]),
            ("tools/cost-small-bands-4096-experimental.txt", "COST",
             [("f", 6), ("B_eff", 7)]),
            ("tools/cost-retuned-4096-experimental.txt", "COST",
             [("f", 6), ("B_eff", 7)]),
        ])
        return 0

    power = inspiral_power(a.n, knee_frac=a.knee)
    expect = a.trials * a.fd
    print("n=%d snr=%.1f fd=%.0e  %d injections a step, %.1f events expected "
          "at the budget%s" % (a.n, a.snr, a.fd, a.trials, expect,
                               "" if expect >= 5 else "  -- TOO FEW TO SEPARATE"))
    print("%6s %8s %8s %7s %10s %10s  %s"
          % ("band", "f", "B_eff", "ratio", "measured", "model", "model is"))
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
