#!/usr/bin/env python3
"""Calibrate the coarse threshold directly. No model anywhere in the loop.

The threshold used to be hmf_threshold(f*g^2, T, fd) -- a Rice model in a
compiled table -- scaled by a margin the accuracy table had measured to
correct it. Two answers to one question, and no way to tell which had moved
when the result was wrong.

This bisects the threshold ITSELF against measured false dismissal, so the
number stored IS the measurement. Nothing is derived from it and nothing
corrects it.

Keyed on (snr, f, band/B_eff): the in-band fraction says how much signal the
band keeps, and the ratio -- samples across the correlation peak -- says how
much of the peak the lag grid can see. Both dimensionless, no n.

Run:  python tools/regen/threshold_4096.py
"""
import multiprocessing as mp
import os
import sys
import time

sys.path.insert(0, "tools")
sys.path.insert(0, "tests")
import hmf_tune as t

from threshold_lowratio import ref_band     # same directory

N = int(sys.argv[1]) if len(sys.argv) > 1 else 4096
#: One definition, shared with the re-measurement tool. These two disagreed
#: once -- this file at n//4, the other at n//8 -- and since a row is not
#: comparable across band (5.5% between 512 and 1024) the comparison of the
#: two silently measured the mismatch and was read as a defect in the rows.
BAND = ref_band(N)
SNRS = [5.0, 5.5, 6.0, 6.5]
#: Extended down to 0.60: band 128 at n=4096 sits at f=0.697,
#: below the old 0.80 floor, so its gate was being extrapolated.
FS = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95, 0.98, 0.995]
#: and down to 1.2: band 128 sits at ratio 1.24.
RATIOS = [1.2, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 16.0]
FDS = [1e-2, 1e-3]
TRIALS = 6000
WORKERS = max(2, (os.cpu_count() or 8) - 2)


def cell(job):
    snr, f, ratio, fd = job
    ref = t.make_ref(N, BAND, f, BAND / ratio)
    # bisect the threshold: higher dismisses more, so walk it down until the
    # measured rate meets the budget. `lo` is always a threshold that passed.
    lo, hi = 0.5 * snr, 1.10 * snr
    best = lo
    for _ in range(9):
        mid = 0.5 * (lo + hi)
        dm, det, _ = t.measure(N, BAND, 1, 8, snr, TRIALS, power=ref,
                               thr=mid)
        if det and dm <= fd:
            best = mid
            lo = mid                       # safe, push the threshold up
        else:
            hi = mid
    return dict(snr=snr, f=f, ratio=ratio, fd=fd, thr=best)


if __name__ == "__main__":
    # Only the cells the table is MISSING, by default. A full sweep
    # re-measures 280 cells to add 21; --only-new computes the new ones and
    # leaves the existing rows alone, which is safe because each cell is an
    # independent bisection -- nothing in the table depends on its
    # neighbours.
    if "--only-new" in sys.argv:
        have = set()
        try:
            for ln in open("python/matchedfilter/threshold.txt"):
                if ln.startswith("THR"):
                    w = ln.split()
                    if int(w[1]) == N:
                        have.add((float(w[2]), float(w[3]), float(w[4]), w[5]))
        except OSError:
            pass
        def fdkey(d):
            return "%.0e" % d
        jobs = [(s, f, r, d) for s in SNRS for f in FS for r in RATIOS
                for d in FDS if (s, f, r, fdkey(d)) not in have]
        print("%d cells already measured; %d new"
              % (len(have), len(jobs)), flush=True)
    else:
        jobs = [(s, f, r, d) for s in SNRS for f in FS
                for r in RATIOS for d in FDS]
    print("%d cells x %d trials x 9 bisection steps, %d workers"
          % (len(jobs), TRIALS, WORKERS), flush=True)
    t0 = time.perf_counter()
    rows = []
    with mp.Pool(WORKERS) as pool:
        for i, r in enumerate(pool.imap_unordered(cell, jobs, chunksize=1)):
            rows.append(r)
            if (i + 1) % 40 == 0:
                el = time.perf_counter() - t0
                print("  %d/%d  %.0fs  eta %.0fs"
                      % (i + 1, len(jobs), el, el/(i+1)*(len(jobs)-i-1)),
                      flush=True)
    out = "tools/regen/threshold_%d.txt" % N
    with open(out, "w") as fh:
        fh.write("# THR n snr f ratio fd threshold\n")
        fh.write("# The coarse threshold, measured. Not modelled, not corrected.\n")
        fh.write("# %d trials a bisection step.\n" % TRIALS)
        for r in sorted(rows, key=lambda x: (x["fd"], x["snr"], x["f"], x["ratio"])):
            fh.write("THR %d %.2f %.4f %.3f %.0e %.4f\n"
                     % (N, r["snr"], r["f"], r["ratio"], r["fd"], r["thr"]))
    print("wrote %s (%d rows) in %.0fs" % (out, len(rows), time.perf_counter()-t0))
