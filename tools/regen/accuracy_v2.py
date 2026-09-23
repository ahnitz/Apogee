"""Regenerate the accuracy table on the measured key.

WHAT CHANGED AND WHY.  The old table was keyed per (n, band) and sampled
B_eff as a FRACTION of the band. Both were wrong, and measurement says so:

  band, at fixed (f, B_eff)   n=8192, f=0.99, B_eff=16
      band  256   512  1024  2048       (band/B_eff 16 to 128)
      dism  1.64  1.88  1.77  1.75 e-2  -> 1.14x, inside the error bars

  n, at fixed (f, B_eff, band)          1024 -> 8192, f=0.99
      4.9x and 4.5x at two B_eff        -> real, and it stays in the key

So band leaves the key entirely: a candidate band enters only through the
(f, B_eff) its own edge produces, which is what selection computes anyway.
Sampling B_eff as band/10 tied the grid to the variable that does not
matter and never reached the small ABSOLUTE values where real references
live -- the FIR-search reference sits at B_eff 1.1 at every band.

The margin dominates everything else -- 90x across 0.97 to 1.00 against
1.6x for 16x of n -- so it gets the finest ladder.
"""
import sys, os, json, time
import multiprocessing as mp
sys.path.insert(0, 'tools')
import hmf_tune as t

NS = [1024, 2048, 4096, 8192]
KS = [4, 8]
SNRS = [5.0, 5.5, 6.0, 6.5]
FS = [0.80, 0.90, 0.95, 0.98, 0.995]
BEFFS = [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0]
MARGINS = [0.90, 0.93, 0.96, 0.98, 1.00]
#: 3x the trials on 1/3 the cells, same wall clock. The leave-one-out
#: error in (f, B_eff) measured 1.44x median on the 6000-trial grid, which
#: is what the Poisson noise of the cells alone predicts -- so the grid was
#: finer than the measurements justified and the spend belongs in trials.
TRIALS = 6000
WORKERS = 30


def band_for(n):
    """One band per length; it is not in the key, it only has to be wide
    enough to hold the largest B_eff and to leave room to decimate."""
    return max(256, min(1024, n // 4))


def cell(job):
    n, K, snr, f, be, mg = job
    band = band_for(n)
    r = t._fdr_cell((n, band, 2, K, snr, f, be, TRIALS, mg))
    r["band_measured_at"] = band
    return r


if __name__ == "__main__":
    jobs = [(n, K, snr, f, be, mg)
            for n in NS for K in KS for snr in SNRS
            for f in FS for be in BEFFS for mg in MARGINS
            if be < band_for(n)]
    jobs.sort(key=lambda j: -j[0])
    print("%d cells, %d workers, %d trials" % (len(jobs), WORKERS, TRIALS),
          flush=True)
    t0 = time.perf_counter()
    rows = []
    with mp.Pool(WORKERS) as pool:
        for i, r in enumerate(pool.imap_unordered(cell, jobs, chunksize=4)):
            rows.append(r)
            if (i + 1) % 400 == 0:
                print("  %d/%d  %.0fs" % (i + 1, len(jobs),
                                          time.perf_counter() - t0), flush=True)
    json.dump(rows, open('/tmp/acc_v2.json', 'w'))
    bad = [r for r in rows if "error" in r]
    print("DONE %d rows (%d errors) %.0fs"
          % (len(rows), len(bad), time.perf_counter() - t0))
    if bad:
        print("  first:", bad[0].get("error"))
