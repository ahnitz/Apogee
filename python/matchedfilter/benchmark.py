"""Self-contained benchmark: `python -m matchedfilter.benchmark`

Needs nothing but numpy, so it runs anywhere the wheel installs.  It compares
against numpy doing the same matched filter - product, inverse transform, then a
per-bin peak scan - which is the work any implementation has to do, and checks
the answers agree before reporting any timing.

numpy's FFT is not a fair proxy for MKL or FFTW; it is a floor, not a rival.
What this is for is telling you whether matchedfilter works and is fast *on your
machine*, since the numbers in the README come from one developer box.

    python -m matchedfilter.benchmark                 # default sweep
    python -m matchedfilter.benchmark --n 4096 16384  # specific lengths
    python -m matchedfilter.benchmark --data 8 --templates 32 --reps 5
"""
import argparse
import platform
import sys
import time

import numpy as np

import matchedfilter as mf


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
    filt = mf.MatchedFilter(n, nd, nt)
    filt.set_data(dspec)
    filt.set_templates(tspec)

    peaks = filt.run(binsize=binsize, window=(ws, we))
    thr = float(np.median(peaks["magnitude"])) * 4.0

    ok = "not checked"
    if check:
        ridx, rmag = _numpy_matched_filter(dspec.astype(np.complex128),
                                           tspec.astype(np.complex128),
                                           binsize, thr, ws, we)
        got = filt.run(binsize=binsize, threshold=thr, window=(ws, we))
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
        filt.run(binsize=binsize, threshold=thr, window=(ws, we))
        best = min(best, time.perf_counter() - t0)

    npy = None
    if check:
        t0 = time.perf_counter()
        _numpy_matched_filter(dspec.astype(np.complex128), tspec.astype(np.complex128),
                              binsize, thr, ws, we)
        npy = time.perf_counter() - t0

    pairs = nd * nt
    return best / pairs * 1e6, (npy / pairs * 1e6 if npy else None), ok


def _inspiral_power(n, frac=0.85, fmax_frac=0.125):
    """An f^(-7/3) spectrum scaled so `frac` of the power sits below n*fmax_frac.

    Fixing the *fraction* rather than the exponent is what keeps the sizes
    comparable: a fixed exponent puts 99% of the power below n/8 at n=2^20 and
    60% at n=2^11, so the lengths would be measuring different problems.
    """
    k = np.arange(1, n // 2, dtype=np.float64)
    p = k ** (-7.0 / 3.0)
    cut = max(2, int(n * fmax_frac))
    tail = p[cut - 1:]
    tail *= (p[:cut - 1].sum() * (1 - frac) / frac) / tail.sum()
    out = np.zeros(n, np.float32)
    out[1:n // 2] = (p / p.sum()).astype(np.float32)
    return out


def _bench_hier(n, nd, nt, snr, fd, reps):
    """Gate vs flat filter on the same pure-noise data.

    Pure noise is the case the gate is built for -- almost nothing survives, so
    the skipped work is real.  On data where every pair triggers the gate can
    only add cost, and the ratio would drop below 1.
    """
    rng = np.random.default_rng(7)
    power = _inspiral_power(n)
    amp = np.sqrt(power)
    h = (amp * np.exp(1j * rng.uniform(0, 2 * np.pi, (nt, n)))).astype(np.complex64)
    h /= np.sqrt((np.abs(h) ** 2).sum(axis=1, keepdims=True))
    d = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)

    flat = mf.MatchedFilter(n, nd, nt)
    flat.set_data(d)
    flat.set_templates(h)

    hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=snr, fd=fd,
                                   band=max(256, n // 8), oversample=2, taps=8)
    hf.set_reference(power)
    hf.set_data(d)
    hf.set_templates(h)

    def best_of(fn):
        fn()
        b = float("inf")
        for _ in range(reps):
            t0 = time.perf_counter()
            fn()
            b = min(b, time.perf_counter() - t0)
        return b

    tf = best_of(lambda: flat.run(binsize=n, threshold=snr))
    th = best_of(lambda: hf.run(binsize=n, threshold=snr))
    return tf, th, hf.trigger_rate


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
    ap.add_argument("--no-hier", action="store_true",
                    help="skip the hierarchical-gate table")
    ap.add_argument("--fd", type=float, default=1e-3,
                    help="false-dismissal budget for the gate")
    a = ap.parse_args(argv)

    print(f"matchedfilter {mf.__version__}   "
          f"{platform.processor() or platform.machine()}   "
          f"backend={mf.backend()}")
    print(f"python {sys.version.split()[0]}   numpy {np.__version__}")
    print(f"{a.data} data x {a.templates} templates = {a.data * a.templates} pairs, "
          f"{a.window:.0%} window\n")
    print(f"  {'n':>8} {'matchedfilter':>12} {'numpy':>12} {'speedup':>9}   check")

    fails = 0
    for n in a.n:
        if not mf.MatchedFilter:
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

    if not a.no_hier:
        print(f"\n\nHierarchical gate vs the flat filter, pure noise, "
              f"false dismissal {a.fd:g}")
        print(f"  {'n':>8} {'snr':>5} {'flat':>11} {'gated':>11} "
              f"{'speedup':>9} {'triggered':>10}")
        for n in a.n:
            for snr in (5.0, 5.5, 6.0, 6.5):
                try:
                    tf, th, rate = _bench_hier(n, a.data, a.templates, snr,
                                               a.fd, a.reps)
                except (ValueError, RuntimeError) as e:
                    print(f"  {n:>8} {snr:>5.1f}   unsupported: {e}")
                    continue
                print(f"  {n:>8} {snr:>5.1f} {tf * 1e3:>10.2f}ms "
                      f"{th * 1e3:>10.2f}ms {tf / th:>8.2f}x {rate:>9.1%}")
        print("\nThe gate skips a pair when a cheap low-band estimate rules out\n"
              "any sample reaching the threshold, so the speedup grows with the\n"
              "threshold and falls to ~1 on data where everything triggers.")

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
