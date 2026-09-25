#!/usr/bin/env python3
"""Regenerate the ACC2 accuracy rows for n=4096 with the oversample gone.

Every shipped row was measured with the odd coarse half present. The filter
no longer computes it, so those rows describe an algorithm that does not
exist -- measured as 9.254% omitted against a 1.000% budget, which is the
guarantee broken outright rather than a tuning drift.

Scoped to n=4096 deliberately: it is the length under test, and the grid at
24000 trials is minutes there. The other lengths keep their old rows until
they are regenerated in turn, which is why this writes only n=4096 and
splices rather than rewriting the file.

Run:  python tools/regen/accuracy_4096_nou.py
"""
import multiprocessing as mp
import os
import sys
import time

sys.path.insert(0, "tools")
import hmf_tune as t

N = 4096
BAND = max(256, min(1024, N // 4))          # as accuracy_v2.band_for
KS = [4, 8]
SNRS = [5.0, 5.5, 6.0, 6.5]
FS = [0.80, 0.90, 0.95, 0.98, 0.995]
BEFFS = [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0]
MARGINS = [0.90, 0.93, 0.96, 0.98, 1.00]
TRIALS = 24000
WORKERS = max(2, (os.cpu_count() or 8) - 2)


def cell(job):
    K, snr, f, be, mg = job
    # The third slot was the oversample. hmf_tune no longer passes it to the
    # filter, so it is inert -- 1 is what actually gets built, and writing 1
    # keeps the record honest.
    r = t._fdr_cell((N, BAND, 1, K, snr, f, be, TRIALS, mg))
    r["band_measured_at"] = BAND
    return r


if __name__ == "__main__":
    jobs = [(K, snr, f, be, mg)
            for K in KS for snr in SNRS for f in FS
            for be in BEFFS for mg in MARGINS if be < BAND]
    print("n=%d band=%d  %d cells x %d trials, %d workers"
          % (N, BAND, len(jobs), TRIALS, WORKERS), flush=True)
    t0 = time.perf_counter()
    rows = []
    with mp.Pool(WORKERS) as pool:
        for i, r in enumerate(pool.imap_unordered(cell, jobs, chunksize=2)):
            rows.append(r)
            if (i + 1) % 100 == 0:
                el = time.perf_counter() - t0
                print("  %d/%d  %.0fs  eta %.0fs"
                      % (i + 1, len(jobs), el, el/(i+1)*(len(jobs)-i-1)),
                      flush=True)
    out = "tools/regen/acc2_4096_nou.txt"
    with open(out, "w") as fh:
        fh.write("# ACC2 rows for n=%d, measured with NO oversample.\n" % N)
        fh.write("# band measured at %d; band is not in the key.\n" % BAND)
        fh.write("# %d trials a cell.\n" % TRIALS)
        for r in sorted(rows, key=lambda x: (x["K"], x["snr"], x["f"],
                                             x["beff_act"], x["margin"])):
            # beff_act, not beff: the shipped rows record the B_eff the
            # reference ACTUALLY had, not the one the grid asked for, and a
            # table mixing the two cannot be spliced or interpolated against.
            fh.write("ACC2 %d %d %.2f %.4f %.2f %.3f %.4e\n"
                     % (N, r["K"], r["snr"], r["f"], r["beff_act"],
                        r["margin"], r["dismissal"]))
    print("wrote %s (%d rows) in %.0fs" % (out, len(rows),
                                           time.perf_counter()-t0))
