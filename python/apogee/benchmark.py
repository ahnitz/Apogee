"""Self-contained benchmark: `python -m apogee.benchmark`

Needs nothing but numpy, so it runs anywhere the wheel installs.  It compares
against numpy doing the same matched filter - product, inverse transform, then a
per-bin peak scan - which is the work any implementation has to do, and checks
the answers agree before reporting any timing.

numpy's FFT is not a fair proxy for MKL or FFTW; it is a floor, not a rival.
What this is for is telling you whether apogee works and is fast *on your
machine*, since the numbers in the README come from one developer box.

    python -m apogee.benchmark                 # default sweep
    python -m apogee.benchmark --n 4096 16384  # specific lengths
    python -m apogee.benchmark --data 8 --templates 32 --reps 5
"""
import argparse
import platform
import sys
import time

import numpy as np

import apogee


def _numpy_matched_filter(dspec, tspec, binsize, threshold, ws, we):
    """Same algorithm, in numpy: product, inverse, per-bin argmax."""
    nd, n = dspec.shape
    nt = tspec.shape[0]
    nb = -(-(we - ws) // binsize)
    idx = np.empty((nd, nt, nb), dtype=np.int64)
    mag = np.empty((nd, nt, nb), dtype=np.float64)
    for d in range(nd):
        for t in range(nt):
            z = np.fft.ifft(dspec[d] * np.conj(tspec[t])) * n
            m = np.abs(z[ws:we])
            pad = nb * binsize - m.size
            if pad:
                m = np.concatenate([m, np.full(pad, -1.0)])
            block = m.reshape(nb, binsize)
            k = block.argmax(axis=1)
            best = block[np.arange(nb), k]
            idx[d, t] = ws + np.arange(nb) * binsize + k
            mag[d, t] = best
    idx[mag <= threshold] = -1
    return idx, mag


def _one(n, nd, nt, binsize, window, reps, check):
    rng = np.random.default_rng(1234)
    d = rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))
    t = rng.standard_normal((nt, n)) + 1j * rng.standard_normal((nt, n))
    # plant a signal so there is something real to find
    d[0] += 4.0 * np.roll(t[0], n // 3)
    dspec = np.fft.fft(d, axis=-1).astype(np.complex64)
    tspec = np.fft.fft(t, axis=-1).astype(np.complex64)

    ws, we = window
    mf = apogee.MatchedFilter(n, nd, nt)
    mf.set_data(dspec)
    mf.set_templates(tspec)

    peaks = mf.run(binsize=binsize, window=(ws, we))
    thr = float(np.median(peaks["magnitude"])) * 4.0

    ok = "not checked"
    if check:
        ridx, rmag = _numpy_matched_filter(dspec.astype(np.complex128),
                                           tspec.astype(np.complex128),
                                           binsize, thr, ws, we)
        got = mf.run(binsize=binsize, threshold=thr, window=(ws, we))
        same = np.array_equal(got["index"], ridx)
        scale = float(rmag.max())
        live = ridx >= 0
        err = float(np.abs(got["magnitude"][live] - rmag[live]).max() / scale) if live.any() else 0.0
        ok = f"indices {'match' if same else 'DIFFER'}, max rel err {err:.1e}"
        if not same or err > 1e-5:
            ok += "   <-- FAILED"

    best = float("inf")
    for _ in range(reps):
        t0 = time.perf_counter()
        mf.run(binsize=binsize, threshold=thr, window=(ws, we))
        best = min(best, time.perf_counter() - t0)

    npy = None
    if check:
        t0 = time.perf_counter()
        _numpy_matched_filter(dspec.astype(np.complex128), tspec.astype(np.complex128),
                              binsize, thr, ws, we)
        npy = time.perf_counter() - t0

    pairs = nd * nt
    return best / pairs * 1e6, (npy / pairs * 1e6 if npy else None), ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, nargs="+",
                    default=[1024, 4096, 16384, 65536],
                    help="transform lengths to test")
    ap.add_argument("--data", type=int, default=8, help="number of data segments")
    ap.add_argument("--templates", type=int, default=8, help="number of templates")
    ap.add_argument("--binsize", type=int, default=0, help="0 picks min(n, 1024)")
    ap.add_argument("--window", type=float, default=0.6,
                    help="fraction of the lag range to search (1.0 = all)")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--no-check", action="store_true",
                    help="skip the numpy cross-check (much faster for large n)")
    a = ap.parse_args(argv)

    print(f"apogee benchmark   {platform.processor() or platform.machine()}")
    print(f"python {sys.version.split()[0]}   numpy {np.__version__}")
    print(f"{a.data} data x {a.templates} templates = {a.data * a.templates} pairs, "
          f"{a.window:.0%} window\n")
    print(f"  {'n':>8} {'apogee':>12} {'numpy':>12} {'speedup':>9}   check")

    fails = 0
    for n in a.n:
        if not apogee.MatchedFilter:
            break
        bs = a.binsize or min(n, 1024)
        if a.window >= 1.0:
            ws, we = 0, n
        else:
            ws = int((1.0 - a.window) * 0.5 * n) & ~15
            we = ws + (int(a.window * n) & ~15)
        try:
            mine, npy, ok = _one(n, a.data, a.templates, bs, (ws, we),
                                 a.reps, not a.no_check)
        except ValueError as e:
            print(f"  {n:>8}   unsupported: {e}")
            continue
        if "FAILED" in ok:
            fails += 1
        sp = f"{npy / mine:.1f}x" if npy else "-"
        npys = f"{npy:.2f}" if npy else "-"
        print(f"  {n:>8} {mine:>11.3f}µs {npys:>11}µs {sp:>9}   {ok}")

    print("\nTimes are microseconds per (data, template) pair, best of "
          f"{a.reps}.\nnumpy is a floor, not a rival - it is here so the "
          "comparison runs anywhere.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
