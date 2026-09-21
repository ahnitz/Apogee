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
import json
import os
import platform
import sys
import time

import numpy as np

import matchedfilter as mf


def available_engines():
    """Which references are installed, without planning anything.

    Listing the columns must not build an FFTW plan: doing so leaves wisdom
    behind, and the plan the benchmark then reports for that size measures
    a cache hit rather than the planning it actually did.
    """
    names = ["numpy"]
    for mod, name in (("pyfftw", "fftw"), ("scipy", "scipy")):
        try:
            __import__(mod)
            names.append(name)
        except Exception:
            pass
    return names


FFTW_PLAN = {"estimate": "FFTW_ESTIMATE", "measure": "FFTW_MEASURE",
             "patient": "FFTW_PATIENT", "exhaustive": "FFTW_EXHAUSTIVE"}
_plan_seconds = {}


def reference_engines(n, fftw_plan="measure"):
    """FFT implementations to compare against, whichever are installed.

    numpy is always present and is a floor rather than a rival.  FFTW is the
    one worth beating, since it is what someone would otherwise reach for; it
    is optional because pyfftw has no wheel everywhere, and a benchmark that
    refuses to run is worse than one that reports less.

    FFTW is driven through a planned pyfftw.FFTW object over pre-allocated
    aligned buffers, not through pyfftw.interfaces.  The interfaces layer adds
    per-call Python work that, at these sizes, made FFTW measure slower than
    numpy -- an unfair comparison, and one that flattered this library.

    The plan is built here, before the caller starts its clock, so planning is
    never inside a reported time.  How long it took is recorded in
    _plan_seconds and printed, so that claim can be checked rather than taken
    on trust.  FFTW_MEASURE is the default because it is what anyone timing
    FFTW would use; --fftw-plan raises or lowers it.
    """
    engines = [("numpy", np.fft.ifft)]
    try:
        import pyfftw
        src = pyfftw.empty_aligned(n, dtype="complex128")
        dst = pyfftw.empty_aligned(n, dtype="complex128")
        _t0 = time.perf_counter()
        plan = pyfftw.FFTW(src, dst, direction="FFTW_BACKWARD",
                           flags=(FFTW_PLAN[fftw_plan],))
        _plan_seconds[n] = time.perf_counter() - _t0

        def fftw_ifft(x, _p=plan, _s=src, _d=dst, _n=float(n)):
            _s[:] = x
            _p()
            return _d / _n          # FFTW's backward transform is unnormalised
        engines.append(("fftw", fftw_ifft))
    except Exception:
        pass
    try:
        from scipy import fft as _sfft
        engines.append(("scipy", _sfft.ifft))
    except Exception:
        pass
    return engines


def _numpy_matched_filter(dspec, tspec, binsize, threshold, ws, we, ifft=None):
    """Same algorithm, via `ifft`: product, inverse, per-bin argmax."""
    ifft = ifft or np.fft.ifft
    nd, n = dspec.shape
    nt = tspec.shape[0]
    nb = -(-(we - ws) // binsize)
    idx = np.empty((nd, nt, nb), dtype=np.int64)
    mag = np.empty((nd, nt, nb), dtype=np.float64)
    for d in range(nd):
        for t in range(nt):
            z = ifft(dspec[d] * np.conj(tspec[t])) * n
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


def _one(n, nd, nt, binsize, window, reps, check, fftw_plan="measure"):
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

    refs = {}
    if check:
        dd, td = dspec.astype(np.complex128), tspec.astype(np.complex128)
        for name, fn in reference_engines(dspec.shape[1], fftw_plan):
            fn(dd[0])                     # warm, after planning
            t0 = time.perf_counter()
            _numpy_matched_filter(dd, td, binsize, thr, ws, we, ifft=fn)
            refs[name] = (time.perf_counter() - t0) / (nd * nt) * 1e6

    pairs = nd * nt
    return best / pairs * 1e6, refs, ok


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


def _same_peaks(a, b, tol=1e-5):
    """Do two back ends report the same peaks?

    Not bit-equality: the targets have different lane counts, so the four-step
    transform sums in a different order and fp32 magnitudes differ in the last
    bit or two.  Measured across AVX3, AVX2 and SSE4 the relative difference
    tops out at 2.7e-7, and about one bin in 3000 picks the other side of a
    tie.  What has to hold is that the same bins reported a peak and the
    magnitudes agree to well inside single precision; an index that moved is
    only acceptable where the magnitude did not.
    """
    ai, am = a[0], a[2]
    bi, bm = b[0], b[2]
    if not np.array_equal(ai >= 0, bi >= 0):
        return False
    m = ai >= 0
    if not m.any():
        return True
    rel = np.abs(am[m] - bm[m]) / np.maximum(np.abs(am[m]), 1e-30)
    return bool(rel.max() <= tol)


def compare_backends(isas, reps, n=4096, ntmpl=64, ntaps=1024,
                     series_len=1 << 20, threshold=5.5):
    """Compare SIMD back ends on a ratio-filter-shaped hierarchical workload.

    This is the shape pycbc's ratio filter drives: a long reference SNR series
    cut into overlap-save blocks, filtered against a batch of FIR templates
    through run_series.  It is the benchmark to judge a back end on.  The flat
    filter exercises only large transforms; this also pays the coarse pass,
    the interpolation, and the per-call cost of many small blocks -- and back
    ends differ more here than they do on the flat path.

    Outputs are compared before anything is timed.
    """
    rng = np.random.default_rng(11)
    k = np.arange(n)
    power = np.zeros(n, np.float32)
    power[1:n // 2] = (k[1:n // 2] ** (-7.0 / 3.0)).astype(np.float32)
    power /= power.sum()
    h = (np.sqrt(power) * np.exp(1j * rng.uniform(0, 2 * np.pi, (ntmpl, n)))
         ).astype(np.complex64)
    h /= np.sqrt((np.abs(h) ** 2).sum(axis=1, keepdims=True))
    series = ((rng.standard_normal(series_len)
               + 1j * rng.standard_normal(series_len))
              / np.sqrt(2)).astype(np.complex64)

    valid, bad = n - ntaps + 1, ntaps // 2
    starts, ws, we, t = [], [], [], 0
    while t + n <= series_len:
        starts.append(t); ws.append(bad); we.append(bad + valid); t += valid
    starts = np.array(starts, np.uintp)
    ws = np.array(ws, np.uintp); we = np.array(we, np.uintp)

    # Injected copy for the comparison only.  Timing runs on the noise series,
    # whose trigger rate is the realistic one; agreeing that a noise series
    # produced no peaks would say nothing about the reconstruction.
    loud = series.copy()
    for j, pos in enumerate(np.linspace(0.05, 0.95, 24)):
        t0 = int(pos * (series_len - n))
        w = np.fft.ifft(np.conj(h[j % ntmpl]))
        loud[t0:t0 + n] += (2000.0 * w / np.linalg.norm(w)).astype(np.complex64)

    plans, ref, agree = {}, None, {}
    for isa in isas:
        try:
            mf.set_target(isa)
        except ValueError:
            continue                    # not in this build, or not runnable here
        p = mf.HierarchicalFilter(n, ndata=1, ntemplates=ntmpl,
                                  snr=threshold, fd=1e-3, band=512,
                                  oversample=2, taps=8)
        p.set_reference(power); p.set_templates(h)
        p.set_first_stage(0.01)
        # run_series returns the plan's own buffers, so copy before the next
        # plan -- or the next call -- overwrites them.
        out = [np.array(a) for a in
               p.run_series(loud, starts, ws, we, binsize=n,
                            threshold=0.0, raw=True)]
        p.set_first_stage(None)
        plans[mf.backend()] = p
        if ref is None:
            ref, agree[mf.backend()] = out, True
        else:
            agree[mf.backend()] = _same_peaks(ref, out)
    mf.set_target(None)
    if not plans:
        return None
    if not (ref[0] >= 0).any():
        raise SystemExit("the comparison pass found no peaks; it would "
                         "report agreement over two empty results")

    names = list(plans)
    tot = {i: 0.0 for i in names}
    for r in range(reps):
        order = names[r % len(names):] + names[:r % len(names)]
        for isa in order:
            t0 = time.perf_counter()
            plans[isa].run_series(series, starts, ws, we, binsize=n,
                                  threshold=threshold, raw=True)
            tot[isa] += time.perf_counter() - t0
    base = tot[names[0]]
    return [(i, tot[i] / reps * 1e3, tot[i] / base, agree[i],
             plans[i].trigger_rate) for i in names]


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


def host_info(label):
    """What a reader needs to interpret the numbers at all.

    A timing without the back end is meaningless -- the dispatcher picks by
    CPU, so the same source runs different kernels on different hosts.
    """
    return {
        "label": label or platform.node(),
        "backend": mf.backend(),
        "machine": platform.machine(),
        "system": platform.system(),
        "release": platform.release(),
        "processor": platform.processor() or platform.machine(),
        "python": sys.version.split()[0],
        "numpy": np.__version__,
        "version": mf.__version__,
        "compiler": platform.python_compiler(),
        "isa_forced": os.environ.get("MF_ISA", ""),
    }


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
    ap.add_argument("--backends", nargs="*", metavar="ISA",
                    help="compare SIMD back ends on a ratio-filter-shaped "
                         "hierarchical workload and exit, e.g. --backends "
                         "AVX3 AVX2 SSE4. Targets that this build "
                         "does not contain are skipped.")
    ap.add_argument("--fd", type=float, default=1e-3,
                    help="false-dismissal budget for the gate")
    ap.add_argument("--json", metavar="PATH",
                    help="also write the results as JSON, for combining runs "
                         "from different machines")
    ap.add_argument("--fftw-plan", default="measure", choices=sorted(FFTW_PLAN),
                    help="FFTW planning effort (default: measure). Planning is "
                         "done before timing starts and is never counted.")
    ap.add_argument("--label", default="",
                    help="name for this machine in a combined report")
    a = ap.parse_args(argv)

    print(f"matchedfilter {mf.__version__}   "
          f"{platform.processor() or platform.machine()}   "
          f"backend={mf.backend()}")
    print(f"python {sys.version.split()[0]}   numpy {np.__version__}")
    print(f"{a.data} data x {a.templates} templates = {a.data * a.templates} pairs, "
          f"{a.window:.0%} window\n")

    if a.backends is not None:
        isas = a.backends or ["AVX3", "AVX2", "SSE4"]
        rows = compare_backends(isas, max(3, a.reps))
        print("SIMD back ends on a ratio-filter-shaped hierarchical run")
        print("  (n=4096, 64 templates, 2^20 series in overlap-save blocks)\n")
        if not rows:
            print("  none of %s are available in this build" % isas)
            return 0
        print("  %-10s %12s %10s %10s  %s"
              % ("back end", "ms/segment", "relative", "triggered", "output"))
        bad = 0
        for isa, ms, rel, same, rate in rows:
            if not same:
                bad += 1
            print("  %-10s %9.2f ms %9.3fx %9.2f%%  %s"
                  % (isa, ms, rel, rate * 100, "matches" if same else "DIFFERS"))
        print("\nOutputs are compared against the first back end before anything\n"
              "is timed: one that disagrees is not a faster back end.")
        return 1 if bad else 0
    engines = available_engines()
    print("  " + f"{'n':>8}" + f"{'matchedfilter':>14}"
          + "".join(f"{e:>11}" for e in engines)
          + "".join(f"{'vs ' + e:>9}" for e in engines) + "   check")
    if "fftw" not in engines:
        print("  (pyfftw not installed; install it for the comparison that matters)")

    fails = 0
    flat_rows = []
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
            mine, refs, ok = _one(n, a.data, a.templates, bs, (ws, we),
                                  a.reps, not a.no_check, a.fftw_plan)
        except ValueError as e:
            print(f"  {n:>8}   unsupported: {e}")
            continue
        if "FAILED" in ok:
            fails += 1
        print("  " + f"{n:>8}" + f"{mine:>12.3f}µs"
              + "".join(f"{refs[e]:>11.2f}" if e in refs else f"{'-':>11}"
                        for e in engines)
              + "".join(f"{refs[e] / mine:>8.1f}x" if e in refs else f"{'-':>9}"
                        for e in engines) + f"   {ok}")
        flat_rows.append({"n": n, "data": a.data, "templates": a.templates,
                          "us_per_pair": mine,
                          "numpy_us_per_pair": refs.get("numpy"),
                          "reference_us_per_pair": refs,
                          "checked": not a.no_check, "ok": "FAILED" not in ok})

    if _plan_seconds:
        tot = sum(_plan_seconds.values())
        print("\nFFTW planning (%s): %s -- excluded from every time above."
              % (FFTW_PLAN[a.fftw_plan],
                 ", ".join("n=%d %.2fs" % (n, t) for n, t in sorted(_plan_seconds.items()))
                 + (" | total %.2fs" % tot)))
    print("\nTimes are microseconds per (data, template) pair, best of "
          f"{a.reps}.\nnumpy is a floor rather than a rival; FFTW is the "
          "comparison that means something.\nEvery reference computes the "
          "whole correlation, while this computes only the binned\nmaxima and "
          "may skip work that cannot produce one -- which is the point of the\n"
          "library, but does mean it is not a like-for-like FFT comparison.")

    hier_rows = []
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
                hier_rows.append({"n": n, "snr": snr, "fd": a.fd,
                                  "data": a.data, "templates": a.templates,
                                  "flat_ms": tf * 1e3, "gated_ms": th * 1e3,
                                  "speedup": tf / th, "trigger_rate": rate})
        print("\nThe gate skips a pair when a cheap low-band estimate rules out\n"
              "any sample reaching the threshold, so the speedup grows with the\n"
              "threshold and falls to ~1 on data where everything triggers.")

    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"host": host_info(a.label),
                       "flat": flat_rows, "hierarchical": hier_rows}, fh, indent=1)
        print(f"\nwrote {a.json}")

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
