#!/usr/bin/env python3
"""Re-measure the coarse-threshold table where it is wrong: low `ratio`.

tools/audit_threshold.py found the shipped rows optimistic below ratio ~5,
by an amount that grows as the ratio falls -- 4% at ratio 2.8, 15% at 1.24
on a realistic reference, 20% at 1.25 on the synthetic family the table
itself was measured on. A threshold above the safe value dismisses signals,
so that is the unsafe direction, and at ratio 1.24 it breaks through into
real false dismissal.

The cause is visible in the rows: at f = 0.5000 they run 3.2441, 3.2500,
3.2148, 3.2383 across ratio 1.2 to 3.0, a flat line with scatter on it
where measurement shows a trend. 6000 trials a bisection step expects six
events at a 1e-3 budget, which cannot place a rate.

So this measures the same cells again with the trial count sized to the
budget, and emits THR rows in the shipped format.

    TRIALS = TARGET_EVENTS / fd

which is why fd=1e-2 cells are ten times cheaper than fd=1e-3 ones and the
default slice does more of them.

RESUMABLE. Rows are appended as they are measured and the output file is
read back on start, so an interrupted run continues where it stopped and a
slice can be widened without redoing what is already there. The full
low-ratio grid -- every n, f, ratio <= 2, snr and fd -- is 1152 cells and
tens of hours; nothing here assumes it completes in one go.

    python tools/regen/threshold_lowratio.py --out /tmp/thr_low.txt
    python tools/regen/threshold_lowratio.py --out /tmp/thr_low.txt \
           --fd 1e-3 --snr 5.0 --ratio 1.2 1.5

AND RE-MEASURING IS NOT SUFFICIENT. The table's key is (n, f, ratio, snr,
fd), and band is left out on the argument that samples across the peak is
band / B_eff with no band left in it. Measured at a fixed (f = 0.70,
ratio = 1.20), realising that ratio at four different bands:

    band    safe threshold      n=4096, snr 5.0, fd 1e-3
     128        2.8078
     256        2.9797
     512        3.1000
    1024        3.2719          16.5% across the band axis alone

The rows are measured at band n/8, so a query at a smaller band gets a
threshold measured for a larger one and dismisses signals, and a query at a
larger band gets a conservative one and merely runs slow. That is the
observed pattern exactly.

It is the coarse maximum, not a fudge: the coarse statistic is a max over
`band` lags and the max of N draws grows like sqrt(2 ln N), so the safe
threshold goes as sqrt(ln band). Normalised at 512 that predicts 2.7339,
2.9227, 3.1000, 3.2677 against the measurements above -- within 2.7%.

So --band is a sweep here, and rows carry the band as a trailing column the
shipped format has no place for. A table that serves every band needs a
third key, or that correction applied at lookup.

Merging into python/matchedfilter/threshold.txt is a SEPARATE step and
deliberately not done here: the rows should be checked with
audit_threshold.py first, which does not share this code path.
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, "tests")
sys.path.insert(0, "tools")
import matchedfilter as mf                          # noqa: E402
import hmf_tune as ht                               # noqa: E402
from test_api import template_with_power, noise     # noqa: E402

#: Events expected at the budget. Below ~10 a bisection step is reading its
#: own scatter, which is how the shipped rows came to be flat in ratio.
TARGET_EVENTS = 12


def measure_cell(n, band, f_target, ratio, snr, fd, trials, steps, nt=16,
                 nb=64, seed=101):
    """Highest coarse threshold whose dismissal meets `fd`, and the features
    the resulting reference actually landed on."""
    power = ht.make_ref(n, band, f_target, band / ratio)
    f, be = mf._band_features(power, band)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    flat = mf.MatchedFilter(n, nb, nt)
    flat.set_templates(H)
    hier = mf.HierarchicalFilter(n, nb, nt, snr=snr, fd=fd, band=band, taps=8)
    hier.set_reference(power)
    hier.set_templates(H)
    ph = np.exp(2j * np.pi * np.arange(n) / n)

    def rate(thr):
        hier.set_coarse_threshold(thr)
        rng = np.random.default_rng(seed)
        detected = omitted = 0
        for _ in range((trials + nb - 1) // nb):
            D = noise((nb, n), rng)
            which = rng.integers(0, nt, nb)
            for b in range(nb):
                lag = int(rng.integers(0, n))
                D[b] += (snr * H[which[b]] * ph ** lag).astype(np.complex64)
            flat.set_data(D)
            hier.set_data(D)
            a = flat.run(binsize=n, threshold=snr)
            c = hier.run(binsize=n, threshold=snr)
            for b in range(nb):
                t = which[b]
                if a["index"][b, t, 0] >= 0:
                    detected += 1
                    omitted += int(c["index"][b, t, 0] < 0)
        return detected, omitted

    # Bracket from below: 2.0 is under every measured threshold in the
    # shipped table, and 1.15x the table value is above the answer wherever
    # the table is optimistic.
    try:
        table = mf.choose_threshold(power, n, snr, fd, band)
    except Exception:
        table = 4.5
    lo, hi = 2.0, table * 1.15
    for _ in range(steps):
        mid = 0.5 * (lo + hi)
        det, om = rate(mid)
        if det > 0 and om / det <= fd:
            lo = mid
        else:
            hi = mid
    return lo, f, be, table


def load_done(path):
    done = set()
    if not os.path.exists(path):
        return done
    for line in open(path):
        p = line.split()
        if len(p) >= 8 and p[0] == "THR":
            done.add((int(p[1]), p[2], p[3], p[4], p[5], int(p[7])))
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="threshold-lowratio.txt")
    ap.add_argument("--n", type=int, nargs="*", default=[4096])
    ap.add_argument("--band", type=int, nargs="*", default=[0],
                    help="bands the ratio is realised at; 0 picks n/8. The "
                         "safe threshold varies 16.5%% across band at a fixed "
                         "(f, ratio) -- the coarse max is over `band` lags "
                         "and grows as sqrt(ln band) -- so a row measured at "
                         "one band does not serve another, and sweeping this "
                         "is what a third table key would need.")
    ap.add_argument("--f", type=float, nargs="*",
                    default=[0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.98, 0.995])
    ap.add_argument("--ratio", type=float, nargs="*", default=[1.2, 1.5])
    ap.add_argument("--snr", type=float, nargs="*", default=[5.0, 5.5, 6.0, 6.5])
    ap.add_argument("--fd", type=float, nargs="*", default=[1e-2])
    ap.add_argument("--steps", type=int, default=7,
                    help="bisection steps; 7 places the answer to <1%%")
    ap.add_argument("--events", type=int, default=TARGET_EVENTS)
    a = ap.parse_args()

    done = load_done(a.out)
    new = 0
    if done:
        print("resuming: %d rows already in %s" % (len(done), a.out))
    fh = open(a.out, "a")
    if not done:
        fh.write("# Re-measured low-ratio coarse thresholds.\n")
        fh.write("# %d events expected at the budget a bisection step, "
                 "%d steps.\n" % (a.events, a.steps))
        fh.write("# n snr f ratio fd threshold band\n")
        fh.flush()
    t_start = time.time()
    todo = [(n, snr, f, r, fd, b) for n in a.n for fd in a.fd
            for snr in a.snr for f in a.f for r in a.ratio for b in a.band]
    print("%d cells requested" % len(todo))
    for (n, snr, f, r, fd, band0) in todo:
        band = band0 or (n // 8)
        # Band is part of the identity of a row even though the shipped
        # format has no column for it, so it goes in the resume key --
        # otherwise a second band silently skips every cell.
        key = (n, "%.2f" % snr, "%.4f" % f, "%.3f" % r, "%.0e" % fd, band)
        if key in done:
            continue
        trials = int(a.events / fd)
        t0 = time.time()
        try:
            safe, f_act, be, table = measure_cell(n, band, f, r, snr, fd,
                                                  trials, a.steps)
        except Exception as e:
            print("  n=%d snr=%.1f f=%.2f ratio=%.1f fd=%.0e  FAILED: %s"
                  % (n, snr, f, r, fd, str(e)[:50]))
            continue
        # The band is a trailing column the shipped format does not have.
        # It is written because the rows are not interchangeable across it;
        # strip it when merging into a table that is still band-blind.
        fh.write("THR %d %.2f %.4f %.3f %.0e %.4f %d\n"
                 % (n, snr, f, r, fd, safe, band))
        fh.flush()
        new += 1
        print("  n=%d snr=%.1f f=%.2f ratio=%.1f fd=%.0e  measured %.4f  "
              "table %.4f  (%+.1f%%)  [%.0fs, %d trials]"
              % (n, snr, f, r, fd, safe, table, 100 * (table / safe - 1),
                 time.time() - t0, trials))
    fh.close()
    print("\n%d new rows in %s  [%.0fs total]"
          % (new, a.out, time.time() - t_start))
    return 0


if __name__ == "__main__":
    sys.exit(main())
