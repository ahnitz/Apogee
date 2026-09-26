#!/usr/bin/env python3
"""The accuracy table: measure it, extend it, query it, check it.

One tool. There were six -- accuracy_v2, accuracy_extend, accuracy_adaptive,
accuracy_4096_nou, accuracy_4096_ratio, accuracy_low_beff -- each a copy of
the same sweep with one axis changed, and they had already drifted: the
shipped table does not reproduce under the current code (see `verify`).

    accuracy.py status                 what is covered, and how well
    accuracy.py measure N [N ...]      measure missing cells and APPEND
    accuracy.py cell N K snr f beff g  one value, measured now
    accuracy.py verify N [--sample S]  re-measure sampled cells vs the table

WHY IT IS FAST NOW. A cell was 12.4s, of which 8.7s (70%) was
np.random.standard_normal and 1.2s (9%) was the filtering it exists to
measure. The sweep was a random number generator with a matched filter
attached.

The fix is not a faster generator -- SFC64 buys 1.14x, float32 buys 1.45x.
It is that the noise is THE SAME EVERY TIME. measure() seeds
default_rng(13) per call, so all 1400 cells at a length draw an identical
sequence, and the sweep regenerated it 1400 times. It is generated once
into shared memory and every worker reads it: 15.90 ms a batch becomes a
0.25 ms copy, 64x.

That the noise is shared across cells is a FEATURE, not a compromise. Cells
are compared against each other -- selection consumes the ranking, not the
absolute rates -- and common random numbers are the standard way to make
such a comparison less noisy. It was already happening by accident of the
fixed seed; this only stops paying for it repeatedly.

The pool is the full trial set for one length: 3.15 GB at n=16384, 12.58 GB
at 65536, one copy for all workers.
"""
import argparse
import multiprocessing as mp
import pathlib
import random
import sys
from multiprocessing import shared_memory

import numpy as np

sys.path.insert(0, "tools")
sys.path.insert(0, "tests")
sys.path.insert(0, "python")
import hmf_tune as t                                            # noqa: E402

#: The grid, inlined from what accuracy_v2.py used so the measured rows
#: stay comparable with the ones already shipped. Band leaves the key
#: entirely: a candidate enters only through the (f, B_eff) its own edge
#: produces, which is what selection computes anyway. B_eff is sampled
#: ABSOLUTELY -- sampling it as a fraction of the band tied the grid to the
#: variable that does not matter and never reached the small values real
#: references live at.
KS = [4, 8]
SNRS = [5.0, 5.5, 6.0, 6.5]
FS = [0.80, 0.90, 0.95, 0.98, 0.995]
BEFFS = [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0]
MARGINS = [0.90, 0.93, 0.96, 0.98, 1.00]

#: Set by what callers ASK FOR. pycbc_inspiral_fir defaults to a 1e-3
#: budget; at 6000 trials the resolution floor is 5e-4, so a 1e-3 request
#: sat barely above the noise. 24000 puts the floor at 1.25e-4.
TRIALS = 24000


def band_for(n):
    """One band per length; not in the key, it only has to be wide enough
    to hold the largest B_eff and leave room to decimate."""
    return max(256, min(1024, n // 4))


OUT = pathlib.Path("python/matchedfilter/accuracy.txt")
WORKERS = 30
SEED = 13                      # what measure() seeds with; the pool must match

_POOL = None                   # (ndarray view, shm) in each worker
_CURSOR = [0]


def pool_shape(n, batch):
    return ((TRIALS + batch - 1) // batch, batch, n)


def build_pool(n, batch):
    """The exact sequence measure() would generate, once.

    Built through the SAME expression the shipped noise() uses, so a pooled
    run and an unpooled run agree bit for bit. Making it cheaper AND
    changing the numbers at the same time would leave no way to tell which
    of the two moved a result.
    """
    nb, b, ln = pool_shape(n, batch)
    shm = shared_memory.SharedMemory(create=True, size=nb * b * ln * 8)
    arr = np.ndarray((nb, b, ln), dtype=np.complex64, buffer=shm.buf)
    rng = np.random.default_rng(SEED)
    for i in range(nb):
        arr[i] = (rng.standard_normal((b, ln))
                  + 1j * rng.standard_normal((b, ln))).astype(np.complex64)
    return arr, shm


def _attach(name, shape):
    global _POOL
    shm = shared_memory.SharedMemory(name=name)
    _POOL = (np.ndarray(shape, dtype=np.complex64, buffer=shm.buf), shm)


def _pooled_noise(shape, rng):
    """Serve measure()'s next batch from the pool.

    measure() calls noise() once per batch in order, so a cursor reproduces
    the sequence exactly. It is reset per cell because every cell restarts
    from the same seed. A copy is returned because the caller injects into
    it in place.
    """
    arr = _POOL[0]
    i = _CURSOR[0]
    _CURSOR[0] += 1
    if i < len(arr) and arr[i].shape == tuple(shape):
        return arr[i].copy()
    return (rng.standard_normal(shape)
            + 1j * rng.standard_normal(shape)).astype(np.complex64)


def _cell(job):
    n, K, snr, f, be, mg = job
    _CURSOR[0] = 0
    r = t._fdr_cell((n, band_for(n), 2, K, snr, f, be, TRIALS, mg))
    r["job"] = job
    return r


def _init(name, shape):
    _attach(name, shape)
    t.noise = _pooled_noise


def read_table():
    rows = []
    for ln in OUT.read_text().splitlines():
        if ln.startswith("ACC2 "):
            w = ln.split()
            rows.append((int(w[1]), int(w[2]), float(w[3]), float(w[4]),
                         float(w[5]), float(w[6]), float(w[7])))
    return rows


#: `taps` does nothing. The CPU stopped interpolating the coarse peak --
#: "execution uses the raw coarse maximum without interpolation" -- and
#: HierarchicalFilter keeps the argument only to key tables measured before
#: that. Measured rather than assumed: across the 3500 cell pairs in the
#: rebuilt table that carry both K=4 and K=8, 3500 are BIT-IDENTICAL. Zero
#: differ.
#:
#: So the axis is measured once and emitted for every K the table format
#: expects. That halves the sweep and changes nothing downstream: the rows
#: are the same rows the old grid produced, and every lookup keyed on K
#: still resolves. If interpolation ever comes back, taps starts mattering
#: again, MEASURE_K has to widen, and tests/test_taps_is_inert.py fails
#: first to say so.
MEASURE_K = KS[:1]


def grid(n):
    return [(n, K, snr, f, be, mg)
            for K in MEASURE_K for snr in SNRS for f in FS
            for be in BEFFS for mg in MARGINS if be < band_for(n)]


def run_jobs(n, jobs, workers=WORKERS):
    batch = t.device_batch(None)
    arr, shm = build_pool(n, batch)
    try:
        with mp.Pool(workers, initializer=_init,
                     initargs=(shm.name, arr.shape)) as pool:
            return list(pool.imap_unordered(_cell, jobs, chunksize=2))
    finally:
        shm.close()
        shm.unlink()


def cmd_status(_):
    rows = read_table()
    print("%-8s %-7s %-9s %-9s" % ("n", "cells", "zero", "median counts"))
    for n in sorted({r[0] for r in rows}):
        v = [r[6] for r in rows if r[0] == n]
        nz = sorted(x for x in v if x > 0)
        print("%-8d %-7d %-9s %-9.1f"
              % (n, len(v), "%d (%.0f%%)" % (sum(1 for x in v if x == 0),
                                             100.0 * sum(1 for x in v if x == 0) / len(v)),
                 (nz[len(nz) // 2] if nz else 0) * TRIALS))
    return 0


def cmd_cell(a):
    batch = t.device_batch(None)
    arr, shm = build_pool(a.n, batch)
    try:
        _attach(shm.name, arr.shape)
        t.noise = _pooled_noise
        _CURSOR[0] = 0
        r = t._fdr_cell((a.n, band_for(a.n), 2, a.K, a.snr, a.f, a.beff,
                         TRIALS, a.gate))
        print("%.4e   (%d trials, %.1f counts)"
              % (r["dismissal"], TRIALS, r["dismissal"] * TRIALS))
    finally:
        shm.close()
        shm.unlink()
    return 0


def cmd_measure(a):
    import time
    have = {(r[0], r[1], r[2], r[3], r[4], r[5]) for r in read_table()
            if r[1] in MEASURE_K}
    for n in a.n:
        jobs = [j for j in grid(n) if j not in have]
        print("n=%d band=%d: %d cells to measure (%d already present)"
              % (n, band_for(n), len(jobs), len(grid(n)) - len(jobs)), flush=True)
        if not jobs:
            continue
        t0 = time.perf_counter()
        rows = run_jobs(n, jobs)
        bad = [r for r in rows if "error" in r]
        if bad:
            print("ABORT n=%d: %d errors, first %s" % (n, len(bad), bad[0]["error"]))
            return 1
        lines = []
        for r in sorted(rows, key=lambda x: x["job"][1:]):
            _, _k, snr, f, be, mg = r["job"]
            for K in KS:                      # one measurement, every K
                lines.append("ACC2 %d %d %.2f %.4f %.2f %.3f %.4e"
                             % (n, K, snr, f, be, mg, r["dismissal"]))
        with OUT.open("a") as fh:
            fh.write("# n=%d, %d trials, shared noise pool. Appended.\n"
                     % (n, TRIALS))
            fh.write("\n".join(lines) + "\n")
        print("  appended %d rows in %.0fs (%.2f s/cell)"
              % (len(lines), time.perf_counter() - t0,
                 (time.perf_counter() - t0) / len(lines)), flush=True)
    return 0


def cmd_verify(a):
    """Re-measure sampled cells and compare with what the table claims."""
    rows = [r for r in read_table() if r[0] == a.n and r[6] > 5e-4]
    if not rows:
        print("n=%d: no resolved rows to check" % a.n)
        return 0
    random.seed(1)
    pick = random.sample(rows, min(a.sample, len(rows)))
    jobs = [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in pick]
    out = {r["job"]: r["dismissal"] for r in run_jobs(a.n, jobs, min(len(jobs), WORKERS))}
    print("%-4s %-5s %-6s %-7s %-5s %-11s %-11s %-6s"
          % ("K", "snr", "f", "beff", "gate", "table", "remeasured", "ratio"))
    ratios = []
    for r in pick:
        got = out[(r[0], r[1], r[2], r[3], r[4], r[5])]
        ratio = r[6] / got if got else float("inf")
        ratios.append(ratio)
        print("%-4d %-5.2f %-6.3f %-7.1f %-5.2f %-11.3e %-11.3e %-6.2f"
              % (r[1], r[2], r[3], r[4], r[5], r[6], got, ratio))
    ok = sum(1 for x in ratios if 0.7 < x < 1.4)
    print("\nwithin 0.7-1.4x: %d/%d" % (ok, len(ratios)))
    return 0 if ok == len(ratios) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    m = sub.add_parser("measure"); m.add_argument("n", type=int, nargs="+")
    m.set_defaults(fn=cmd_measure)
    c = sub.add_parser("cell")
    for name, typ in (("n", int), ("K", int), ("snr", float),
                      ("f", float), ("beff", float), ("gate", float)):
        c.add_argument(name, type=typ)
    c.set_defaults(fn=cmd_cell)
    v = sub.add_parser("verify"); v.add_argument("n", type=int)
    v.add_argument("--sample", type=int, default=14)
    v.set_defaults(fn=cmd_verify)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
