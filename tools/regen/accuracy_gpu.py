#!/usr/bin/env python3
"""Measure the accuracy table for the GPU's algorithm.

The shipped accuracy.txt was measured with the CPU filtering, and the GPU
does not run the CPU's algorithm: where the CPU interpolates the coarse
peak, the GPU escalates the whole interpolation window, so it refines a
superset of the CPU's pairs and dismisses less. Sharing the table has been
safe only in that direction -- the CPU's rate is an upper bound on a
strictly more conservative path -- and safe is not the same as right. The
GPU is currently calibrated for something more aggressive than it runs, and
pays for it in refinement it did not need.

Same grid as accuracy_v2.py, same trials, same band_for -- the point is a
table that differs from the shipped one ONLY in which implementation
produced the numbers. The lengths are the ones the GPU backend actually
runs; above 16384 it has no algorithm to characterise and accuracy.txt
continues to serve.

Workers: the cells queue on one device, but a cell is about 95% numpy
building noise and injections and about 5% filtering, so the pool still
pays. Each worker carries its own device context, so this is not the CPU
sweep's worker count.

    python tools/regen/accuracy_gpu.py            # writes /tmp/acc_gpu.json
    python tools/regen/emit_acc2.py /tmp/acc_gpu.json > accuracy-gpu.txt

Nothing reads accuracy-gpu.txt until it is put in python/matchedfilter/;
accuracy_table_for picks it up from there and the CPU keeps accuracy.txt.
"""
import json
import multiprocessing as mp
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hmf_tune as t

#: Only what the GPU backend runs. _GPU_SIZES also holds 64..512, which the
#: accuracy grid never reaches because band_for(n) needs room to decimate.
NS = [1024, 2048, 4096, 8192, 16384]
KS = [4, 8]
SNRS = [5.0, 5.5, 6.0, 6.5]
FS = [0.80, 0.90, 0.95, 0.98, 0.995]
BEFFS = [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0]
MARGINS = [0.90, 0.93, 0.96, 0.98, 1.00]
TRIALS = 24000
DEVICE = "gpu"
WORKERS = int(os.environ.get("MF_TUNE_WORKERS", "8"))


def band_for(n):
    return t_band(n)


def t_band(n):
    """Same rule as accuracy_v2.band_for, so the grids line up cell for cell."""
    return max(256, min(1024, n // 4))


def cell(job):
    n, K, snr, f, be, mg = job
    band = t_band(n)
    r = t._fdr_cell((n, band, 2, K, snr, f, be, TRIALS, mg, DEVICE))
    r["band_measured_at"] = band
    return r


if __name__ == "__main__":
    jobs = [(n, K, snr, f, be, mg)
            for n in NS for K in KS for snr in SNRS
            for f in FS for be in BEFFS for mg in MARGINS
            if be < t_band(n)]
    jobs.sort(key=lambda j: -j[0])
    print("%d cells, %d workers, %d trials, device=%s"
          % (len(jobs), WORKERS, TRIALS, DEVICE), flush=True)
    t0 = time.perf_counter()
    rows = []
    with mp.Pool(WORKERS) as pool:
        for i, r in enumerate(pool.imap_unordered(cell, jobs, chunksize=2)):
            rows.append(r)
            if (i + 1) % 50 == 0:
                done = time.perf_counter() - t0
                print("  %d/%d  %.0fs elapsed, ~%.0fs left"
                      % (i + 1, len(jobs), done,
                         done * (len(jobs) - i - 1) / (i + 1)), flush=True)
    json.dump(rows, open("/tmp/acc_gpu.json", "w"))
    bad = [r for r in rows if "error" in r]
    print("DONE %d rows (%d errors) %.0fs"
          % (len(rows), len(bad), time.perf_counter() - t0))
    if bad:
        print("  first:", bad[0].get("error"))
