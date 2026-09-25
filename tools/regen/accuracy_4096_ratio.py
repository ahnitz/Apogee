#!/usr/bin/env python3
"""ACC2 rows for n=4096, no oversample, keyed on SAMPLES ACROSS THE PEAK.

The old grid sampled B_eff absolutely, 2 to 128, and measured every cell at
band 1024. Real references have B_eff 154 to 384, so every lookup for one was
an extrapolation -- and worse, the quantity scalloping actually depends on is
neither band nor B_eff but their RATIO:

    correlation peak width in lag  ~  n / B_eff
    coarse lag step                =  n / band
    samples across the peak        =  band / B_eff      (dimensionless, no n)

The old grid covered ratio 8 to 512. The reference this library is for sits
at 1.66 at band 256, 2.83 at band 512, 5.33 at band 1024. With the oversample
present that doubled to 3.3-10.7 and the undersampling was survivable; with
it gone, 1.66 samples across a peak is critically undersampled and dismissal
goes 12x.

So the grid is measured AT the ratio, by choosing B_eff = band / ratio, and
the key records the ratio. Covering 1 to 32 puts the real operating points
inside the measured region instead of beyond its edge.

Run:  python tools/regen/accuracy_4096_ratio.py
"""
import multiprocessing as mp
import os
import sys
import time

sys.path.insert(0, "tools")
import hmf_tune as t

N = 4096
BAND = 1024                      # where the cells are measured; not in the key
KS = [4, 8]
SNRS = [5.0, 5.5, 6.0, 6.5]
FS = [0.80, 0.90, 0.95, 0.98, 0.995]
#: samples across the correlation peak. 1.5-6 is where real references live.
RATIOS = [1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 16.0, 32.0]
MARGINS = [0.90, 0.93, 0.96, 0.98, 1.00]
TRIALS = 24000
WORKERS = max(2, (os.cpu_count() or 8) - 2)


def cell(job):
    K, snr, f, ratio, mg = job
    be = BAND / ratio
    r = t._fdr_cell((N, BAND, 1, K, snr, f, be, TRIALS, mg))
    r["ratio_req"] = ratio
    return r


if __name__ == "__main__":
    jobs = [(K, snr, f, ra, mg)
            for K in KS for snr in SNRS for f in FS
            for ra in RATIOS for mg in MARGINS]
    print("n=%d band=%d  %d cells x %d trials, %d workers"
          % (N, BAND, len(jobs), TRIALS, WORKERS), flush=True)
    t0 = time.perf_counter()
    rows = []
    with mp.Pool(WORKERS) as pool:
        for i, r in enumerate(pool.imap_unordered(cell, jobs, chunksize=2)):
            rows.append(r)
            if (i + 1) % 150 == 0:
                el = time.perf_counter() - t0
                print("  %d/%d  %.0fs  eta %.0fs"
                      % (i + 1, len(jobs), el, el/(i+1)*(len(jobs)-i-1)),
                      flush=True)
    good = [r for r in rows if "dismissal" in r]
    out = "tools/regen/acc2_4096_ratio.txt"
    with open(out, "w") as fh:
        fh.write("# ACC2R rows: n=%d, NO oversample, keyed on band/B_eff.\n" % N)
        fh.write("# measured at band %d; %d trials a cell.\n" % (BAND, TRIALS))
        fh.write("# ACC2R n K snr f ratio margin dismissal\n")
        for r in sorted(good, key=lambda x: (x["K"], x["snr"], x["f"],
                                             x["ratio_req"], x["margin"])):
            # the ratio the reference ACTUALLY had, from its measured B_eff
            ra = BAND / r["beff_act"] if r["beff_act"] else r["ratio_req"]
            fh.write("ACC2R %d %d %.2f %.4f %.3f %.3f %.4e\n"
                     % (N, r["K"], r["snr"], r["f"], ra,
                        r["margin"], r["dismissal"]))
    print("wrote %s (%d of %d cells) in %.0fs"
          % (out, len(good), len(rows), time.perf_counter()-t0))
