#!/usr/bin/env python3
"""Where the error in a predicted dismissal actually comes from.

Four contributions, separated because they have different fixes:

  1. Poisson  -- each cell is a finite count. Fix: more trials.
  2. (f, B_eff) interpolation -- predict a cell from its neighbours with
     that cell held out. Fix: denser grid in f / B_eff.
  3. margin interpolation -- same, along the margin axis, which is the
     steep one. Fix: denser margin ladder.
  4. margin PLACEMENT -- the quantity selection actually uses: solve for
     the margin meeting a budget, from a curve with one point removed.
"""
import sys, math, argparse, collections
import numpy as np
sys.path.insert(0, 'tools')
import matchedfilter as mf


def load(path):
    rows = collections.defaultdict(list)
    for line in open(path):
        if not line.startswith("ACC2"):
            continue
        q = line.split()
        rows[(int(q[1]), int(q[2]), float(q[3]), float(q[6]))].append(
            (float(q[4]), float(q[5]), float(q[7])))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    ap.add_argument("--trials", type=int, default=6000)
    a = ap.parse_args()
    rows = load(a.table)
    floor = 3.0 / a.trials

    # 1. Poisson, for the cells that carry the decision
    res = [v for cells in rows.values() for (_, _, v) in cells if v > 0]
    res = np.array(res)
    det = 0.7 * a.trials
    cnt = res * det
    ok = cnt >= 1
    print("1. Poisson error on a measured cell")
    for lo, hi, name in ((1e-2, 1.0, "dismissal >= 1e-2"),
                         (1e-3, 1e-2, "1e-3 to 1e-2"),
                         (0.0, 1e-3, "below 1e-3")):
        m = (res >= lo) & (res < hi) & ok
        if m.sum():
            print("   %-20s n=%-5d median +-%.0f%%"
                  % (name, m.sum(), 100 * np.median(1.0 / np.sqrt(cnt[m]))))

    # 2. leave-one-out in (f, B_eff)
    errs = []
    for key, cells in rows.items():
        if len(cells) < 5:
            continue
        for i, (f, be, v) in enumerate(cells):
            if v <= floor:
                continue
            rest = cells[:i] + cells[i + 1:]
            pred = mf._idw(rest, f, be, log=True, floor=floor)
            if pred and pred > 0:
                errs.append(abs(math.log10(pred / v)))
    errs = np.array(errs)
    print("\n2. (f, B_eff) interpolation, leave-one-out  (n=%d)" % len(errs))
    print("   median %.2fx   p90 %.2fx" % (10 ** np.median(errs),
                                           10 ** np.percentile(errs, 90)))

    # 3. margin axis, leave-one-out
    bym = collections.defaultdict(dict)
    for (n, K, snr, mg), cells in rows.items():
        for (f, be, v) in cells:
            bym[(n, K, snr, round(f, 4), round(be, 2))][mg] = v
    errs = []
    for curve in bym.values():
        ms = sorted(curve)
        if len(ms) < 3:
            continue
        for i in range(1, len(ms) - 1):
            lo, mid, hi = ms[i - 1], ms[i], ms[i + 1]
            a_, b_, c_ = curve[lo], curve[mid], curve[hi]
            if min(a_, b_, c_) <= floor:
                continue
            w = (mid - lo) / (hi - lo)
            pred = 10 ** (math.log10(a_) + w * (math.log10(c_) - math.log10(a_)))
            errs.append(abs(math.log10(pred / b_)))
    errs = np.array(errs)
    print("\n3. margin interpolation, leave-one-out  (n=%d)" % len(errs))
    if len(errs):
        print("   median %.2fx   p90 %.2fx" % (10 ** np.median(errs),
                                               10 ** np.percentile(errs, 90)))

    # 4. what selection actually does: place the margin for a budget
    print("\n4. margin PLACEMENT error (what selection uses)")
    for fd in (1e-2, 1e-3):
        dm = []
        for curve in bym.values():
            ms = sorted(curve)
            if len(ms) < 4:
                continue
            full = [(m, curve[m]) for m in ms]
            got_full = mf._margin_at_budget(full, fd, floor)
            for i in range(1, len(ms) - 1):
                part = [(m, curve[m]) for m in ms if m != ms[i]]
                got_part = mf._margin_at_budget(part, fd, floor)
                if got_full is not None and got_part is not None:
                    dm.append(abs(got_part - got_full))
        if dm:
            dm = np.array(dm)
            print("   fd=%.0e: margin shifts median %.4f, p90 %.4f"
                  % (fd, np.median(dm), np.percentile(dm, 90)))
            print("            -> FDR factor median %.2fx, p90 %.2fx"
                  % (10 ** (53 * np.median(dm)), 10 ** (53 * np.percentile(dm, 90))))


if __name__ == "__main__":
    main()
