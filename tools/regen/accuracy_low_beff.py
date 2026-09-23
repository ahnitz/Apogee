"""Extend the accuracy table down the falling branch of the B_eff U-curve.

The shipped grid is laddered in FRACTIONS of the band, so its floor sits at
about band/10 -- 25.6 at band 256, 3328 at band 32768. Dismissal is U-shaped
in B_eff and the bad branch is at small ABSOLUTE values, which the ladder
never reaches. Real references live there: the FIR-search reference is at
B_eff 1.1 and the tests' inspiral reference at 1.9, at every band.

Only f=0.99 is measured. Dismissal rises with f, so an f=0.99 row is the
conservative one for any query at or below it, and references that are
concentrated enough to have low B_eff have high f by construction.
"""
import sys, os, json, time
import multiprocessing as mp
sys.path.insert(0, 'tools')
import hmf_tune as t

NS = [1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144]
BEFFS = [1.2, 3.5]
KS = [4, 8]
MARGINS = [0.90, 0.94, 0.97, 1.00]
SNRS = [5.0, 5.5, 6.0]
#: The shipped table's own per-length trial counts. Matching them keeps one
#: resolution floor across the table; 4000 everywhere would be finer at the
#: large lengths and 3.8 hours of wall clock against about an hour here, for
#: rows whose values are 1e-2 and up anyway.
TRIALS = {1024: 4000, 2048: 4000, 4096: 4000, 8192: 4000, 16384: 4000,
          32768: 2500, 65536: 2500, 131072: 1500, 262144: 1500}
F = 0.99
WORKERS = 30


def bands_of(n):
    return [b for b in (256, 512, 1024, 2048, 4096, 8192, 16384, 32768,
                        65536, 131072) if b < n]


if __name__ == "__main__":
    jobs = []
    for n in NS:
        for band in bands_of(n):
            for be in BEFFS:
                if be >= band:
                    continue
                for K in KS:
                    for snr in SNRS:
                        for mg in MARGINS:
                            jobs.append((n, band, 2, K, snr, F, be, TRIALS[n], mg))
    jobs.sort(key=lambda j: -j[0])
    print("%d cells, %d workers" % (len(jobs), WORKERS), flush=True)
    t0 = time.perf_counter()
    rows = []
    with mp.Pool(WORKERS) as pool:
        for i, r in enumerate(pool.imap_unordered(t._fdr_cell, jobs, chunksize=1)):
            rows.append(r)
            if (i + 1) % 100 == 0:
                print("  %d/%d  %.0fs" % (i + 1, len(jobs),
                                          time.perf_counter() - t0), flush=True)
    json.dump(rows, open('/tmp/lowbeff_rows.json', 'w'))
    bad = [r for r in rows if "error" in r]
    print("DONE %d rows (%d errors) in %.0fs"
          % (len(rows), len(bad), time.perf_counter() - t0))
    if bad:
        print("  first error:", bad[0]["error"])
