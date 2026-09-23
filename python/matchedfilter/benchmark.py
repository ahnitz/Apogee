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
    for mod, name in (("pyfftw", "fftw"), ("scipy", "scipy"),
                      ("mkl_fft", "mkl")):
        try:
            __import__(mod)
            names.append(name)
        except Exception:
            pass
    return names


FFTW_PLAN = {"estimate": "FFTW_ESTIMATE", "measure": "FFTW_MEASURE",
             "patient": "FFTW_PATIENT", "exhaustive": "FFTW_EXHAUSTIVE"}
_plan_seconds = {}
_plan_used = {}

#: Largest transform planned with FFTW_PATIENT under --fftw-plan auto.
#: Zero means measure everywhere, which is the default.
#:
#: Patient does produce a faster plan -- 26% at n=4096 (7.19 against 9.73 us)
#: and 26% at n=16384 (57.3 against 77.1) -- but it costs far too much to
#: plan: 22s at n=4096 and 180s at n=65536, against 1.4s for measure. A
#: benchmark that spends minutes planning before it measures anything is not
#: one CI can run.
#:
#: FFTW_MEASURE is also what anyone timing FFTW would actually use, so it is
#: the honest default. The instability that first looked like a planning
#: problem -- 9.73 us and 24.56 us on two runs of the same size -- was the
#: ESTIMATOR: a single timed call, min over repeats, on a loaded machine.
#: With a duration floor and a median it is steady. Raise this, or pass
#: --fftw-plan patient, to give FFTW its best showing at small sizes.
PATIENT_MAX_N = 0


def plan_for(n, mode):
    """Which FFTW planning flag to use at this size."""
    if mode != "auto":
        return mode
    return "patient" if n <= PATIENT_MAX_N else "measure"


def reference_transforms(n, batch, x, fftw_plan="auto"):
    """Zero-argument callables, each doing one batched inverse transform.

    Bound to `x` up front so that what gets timed is the transform and not the
    plumbing around it. That matters most for FFTW: it works out of its own
    aligned buffers, so copying into them and normalising afterwards are costs
    of the harness rather than of the transform, and charging them to FFTW
    made it measure slower than numpy, which is not a result anyone should
    believe.
    """
    out = [("numpy", lambda: np.fft.ifft(x, axis=-1))]
    try:
        import pyfftw
        # complex64, to match what this library computes in. An earlier
        # version planned complex128 and timed the references on doubled-up
        # copies of the data, so every reference did twice the arithmetic --
        # which flattered this library about 2x and was not the same
        # computation. threads=1 because this library is single-threaded and
        # a threaded reference compares core counts.
        src = pyfftw.empty_aligned((batch, n), dtype="complex64")
        dst = pyfftw.empty_aligned((batch, n), dtype="complex64")
        _t0 = time.perf_counter()
        plan = pyfftw.FFTW(src, dst, axes=(-1,), direction="FFTW_BACKWARD",
                           flags=(FFTW_PLAN[plan_for(n, fftw_plan)],),
                           threads=1, normalise_idft=True)
        _plan_used[n] = plan_for(n, fftw_plan)
        _plan_seconds[n] = time.perf_counter() - _t0
        src[:] = x
        out.append(("fftw", plan))
    except Exception:
        pass
    try:
        from scipy import fft as _sfft
        out.append(("scipy", lambda: _sfft.ifft(x, axis=-1, workers=1)))
    except Exception:
        pass
    try:
        # Intel MKL, where it exists. x86-only and not packaged for arm64 or
        # macOS, so its absence is normal rather than a problem -- the
        # benchmark reports whichever references it finds.
        from mkl_fft.interfaces import numpy_fft as _mkl
        try:
            # Single-threaded, like every other engine here. MKL defaults to
            # every core, and a threaded reference compares core counts.
            # Optional: the runtime module is not always importable even when
            # mkl_fft is, and MKL_NUM_THREADS covers it either way.
            import mkl as _mklrt
            _mklrt.set_num_threads(1)
        except Exception:
            pass
        out.append(("mkl", lambda: _mkl.ifft(x, axis=-1)))
    except Exception:
        pass
    return out


def reference_transform_us(n, batch, reps, fftw_plan="auto"):
    """Microseconds for ONE inverse transform, and nothing else.

    What this measures, and what it deliberately does not: the reference
    number is the inverse FFT alone -- no product, no magnitude, no peak scan
    -- batched, single precision, one thread. matchedfilter's number covers
    all of it. So the comparison is this library's whole job against the
    single step that normally dominates it, and that asymmetry is the point
    rather than a flaw: it is not an FFT library, and the question a reader
    has is whether skipping the rest of the correlation beats doing the
    transform at all.

    An earlier version timed the references through a Python loop calling
    ifft once per pair with temporaries around it. At n=1024 that read 30.5
    us/pair against 8.6 batched -- 3.6x of Python overhead reported as FFT
    time, on top of the precision mistake above.
    """
    rng = np.random.default_rng(7)
    x = (rng.standard_normal((batch, n))
         + 1j * rng.standard_normal((batch, n))).astype(np.complex64)
    out = {}
    for name, fn in reference_transforms(n, batch, x, fftw_plan):
        try:
            fn()                        # warm, after planning
            # Median of repeats, each repeated to a duration floor -- the same
            # estimator the hierarchical side uses. Min-of-reps on a single
            # call reported 9.73 us and 24.56 us on two runs of the same size
            # under load, which is the estimator failing rather than FFTW.
            ts = []
            for _ in range(max(5, reps)):
                k, t0 = 1, time.perf_counter()
                fn()
                dt = time.perf_counter() - t0
                while dt < 0.02:
                    k *= 2
                    t0 = time.perf_counter()
                    for _ in range(k):
                        fn()
                    dt = time.perf_counter() - t0
                ts.append(dt / k)
            out[name] = float(np.median(ts)) / batch * 1e6
        except Exception:
            continue
    return out


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

    # Reference: the inverse transform alone, batched, single precision, one
    # thread. Capped so a 2^18 transform does not need a gigabyte to time.
    rbatch = int(min(nd * nt, max(4, 2 ** 22 // n)))
    refs = reference_transform_us(n, rbatch, reps, fftw_plan)

    pairs = nd * nt
    return best / pairs * 1e6, refs, ok


def _inspiral_power(n, frac=0.895, fmax_frac=0.125, knee_frac=0.0150):
    """Expected matched-filter OUTPUT power, as set_reference wants it.

    This is |h(f)|^2 / S(f), NOT |h(f)|^2. The distinction is the one the
    documentation warns callers about, and this function got it wrong: it
    returned the raw f^(-7/3) signal power, which peaks in bin 1 and puts half
    its power there. Measured on that, the effective bandwidth at band 256 was
    1.9 bins against 141 for a real captured reference -- 74x too narrow.

    Effective bandwidth is what sets how sharp the correlation peak is, and a
    2-bin reference gives a maximally broad peak that the coarse lag grid
    catches for free. So the hierarchical benchmark was measuring a best case
    that no real search sees: it selected band 256 at snr 6 and reported 13x,
    where the captured reference needs band 512 there.

    The noise wall is what fixes it. S(f) rises steeply below the seismic
    knee, so the output power peaks inside the band rather than at DC. With
    the knee at 1.9% of the band this reproduces a real reference closely --
    B_eff 177 against 141 at band 256, peak bin 72 against 78, half the power
    below bin 108 against 122.

    `frac` still fixes how much power sits below `fmax_frac`, because a fixed
    exponent alone would put 99% below n/8 at n=2^20 and 60% at n=2^11, so the
    lengths would be measuring different problems. Its value and the knee are
    FITTED to the captured reference rather than chosen: least squares on
    (f, B_eff) at bands 256/512/1024 gives frac=0.895, knee=0.0150 and a 4.9%
    rms relative error --

        band      this model            captured
        256       0.8248 / 154.4        0.7956 / 141.4
        512       0.8950 / 180.8        0.9335 / 190.2
        1024      0.9702 / 211.8        0.9875 / 212.5

    The previous frac=0.85 was inherited, and it mattered: it put 85% of the
    power below n/8 where a real reference has 93%, which lowered the coarse
    threshold enough to escalate 18.8% of pure-noise pairs against 1.2% on the
    captures at the same band and margin.
    """
    k = np.arange(1, n // 2, dtype=np.float64)
    knee = max(2.0, knee_frac * n)
    p = k ** (-7.0 / 3.0) / ((knee / k) ** 4 + 1.0)
    cut = max(2, int(n * fmax_frac))
    tail = p[cut - 1:]
    if tail.size and tail.sum() > 0:
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
        def build():
            q = mf.HierarchicalFilter(n, ndata=1, ntemplates=ntmpl,
                                      snr=threshold, fd=1e-3, band=512,
                                      oversample=2, taps=8)
            q.set_reference(power); q.set_templates(h)
            return q

        # Separate plans for the two passes.  refine_rate counts over a
        # plan's whole lifetime, so running the injected comparison on the
        # plan that is about to be timed reports a blend of the two.
        c = build()
        c.set_first_stage(0.01)
        # run_series returns the plan's own buffers, so copy before the next
        # call overwrites them.
        out = [np.array(a) for a in
               c.run_series(loud, starts, ws, we, binsize=n,
                            threshold=0.0, raw=True)]
        plans[mf.backend()] = build()
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
             plans[i].refine_rate) for i in names]


def _bench_hier(n, nd, nt, snr, fd, reps):
    """Coarse threshold vs flat filter on the same pure-noise data.

    Pure noise is the case the coarse threshold is built for -- almost nothing survives, so
    the skipped work is real.  On data where every pair triggers the coarse threshold can
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

    # No band, no oversample, no taps: the library picks them from the
    # reference and the threshold, which is the thing worth benchmarking.
    # Pinning band=n//8 here meant the same first stage ran at every
    # threshold, so the plotted speedup could not show what a higher
    # threshold buys -- a narrower first pass and a tighter margin -- and it
    # measured a configuration no caller would get.
    hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=snr, fd=fd)
    hf.set_reference(power)
    hf.set_data(d)
    hf.set_templates(h)

    def per_call(fn, floor=0.02):
        """Seconds per call, repeating until the timer has something to bite on.

        At n=1024 one call is tens of microseconds, so a single perf_counter
        interval is mostly clock resolution and call overhead. Repeating to a
        fixed floor makes the small and large lengths equally trustworthy
        without making the large ones slow.
        """
        fn()
        k = 1
        while True:
            t0 = time.perf_counter()
            for _ in range(k):
                fn()
            dt = time.perf_counter() - t0
            if dt >= floor:
                return dt / k
            k = max(2 * k, int(k * floor / max(dt, 1e-9)) + 1)

    # Interleaved, and the ratio taken per rep. Timing the flat filter to
    # completion and then the hierarchical one put any drift between the two
    # loops straight into the speedup -- on a shared CI runner that is the
    # dominant error. Within a rep the two run back to back under the same
    # conditions, so clock and neighbours are common to both and cancel.
    # Same lag window the flat benchmark uses. Searching all n lags, as this
    # did, is not something an overlap-save search does -- the wrap-around
    # region is invalid -- and it inflates the coarse pass's work: every extra
    # lag is another chance for a noise sample to clear the coarse threshold
    # and force a reconstruction that a real search would never have asked
    # for. Measured at n=4096, band 512: 18.8% of pure-noise pairs escalated
    # over all lags against 6.2% over a realistic window.
    ws = int(0.2 * n) & ~15
    we = ws + (int(0.6 * n) & ~15)
    flat_run = lambda: flat.run(binsize=n, threshold=snr, window=(ws, we))
    hier_run = lambda: hf.run(binsize=n, threshold=snr, window=(ws, we))
    tfs, ths, ratios = [], [], []
    for _ in range(max(3, reps)):
        a = per_call(flat_run)
        b = per_call(hier_run)
        tfs.append(a)
        ths.append(b)
        ratios.append(a / b)
    # Median of the per-rep ratios, not a ratio of medians: one descheduled
    # rep then moves one sample instead of biasing the result.
    tf, th = float(np.median(tfs)), float(np.median(ths))
    return tf, th, hf.refine_rate, hf.config, float(np.median(ratios))


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
                    help="skip the hierarchical table")
    ap.add_argument("--backends", nargs="*", metavar="ISA",
                    help="compare SIMD back ends on a ratio-filter-shaped "
                         "hierarchical workload and exit, e.g. --backends "
                         "AVX3 AVX2 SSE4. Targets that this build "
                         "does not contain are skipped.")
    ap.add_argument("--fd", type=float, default=1e-3,
                    help="false-dismissal budget for the coarse threshold")
    ap.add_argument("--json", metavar="PATH",
                    help="also write the results as JSON, for combining runs "
                         "from different machines")
    ap.add_argument("--fftw-plan", default="auto",
                    choices=sorted(FFTW_PLAN) + ["auto"],
                    help="FFTW planning effort. Default auto: patient up to "
                         "n=%d, measure above. Planning happens before timing "
                         "starts and is never counted." % PATIENT_MAX_N)
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
        print("\nFFTW planning, excluded from every time above: %s | total "
              "%.2fs.\n%s"
              % (", ".join("n=%d %s %.2fs"
                           % (n, _plan_used.get(n, "?"), t)
                           for n, t in sorted(_plan_seconds.items())), tot,
                 "FFTW_PATIENT is 26%% faster than FFTW_MEASURE where it is\n"
                 "affordable, and far steadier -- measure returned 9.73 and\n"
                 "24.56 us on two runs at n=4096. It is used up to n=%d; above\n"
                 "that it does not finish planning in reasonable time (180s at\n"
                 "n=65536 against 1.4s for measure)." % PATIENT_MAX_N))
    print("\n" + "The reference columns time ONE INVERSE TRANSFORM and nothing\n"
          "else -- batched, single precision, one thread. This library's column\n"
          "covers the whole matched filter: the product, the transform and the\n"
          "peak scan. So the ratio is this library's entire job against the one\n"
          "step that normally dominates it. That is the honest framing -- it is\n"
          "not an FFT library and does not implement a general FFT -- and it is\n"
          "why the ratio is a statement about the algorithm rather than about\n"
          "anyone's transform being slow.")

    hier_rows = []
    if not a.no_hier:
        print(f"\n\nHierarchical vs flat filter, pure noise, "
              f"false dismissal {a.fd:g}")
        print(f"  {'n':>8} {'snr':>5} {'flat':>11} {'hierarchical':>11} "
              f"{'speedup':>9} {'triggered':>10} {'chosen':>14}")
        for n in a.n:
            for snr in (5.0, 5.5, 5.75, 6.0, 6.5):
                try:
                    tf, th, rate, cfg, speed = _bench_hier(
                        n, a.data, a.templates, snr, a.fd, a.reps)
                except (ValueError, RuntimeError) as e:
                    # An uncovered (n, snr, fd) is a refusal, not a failure:
                    # the tables are measured and the library will not answer
                    # outside them. Report it as a gap in coverage.
                    first = str(e).strip().split("\n")[0]
                    print(f"  {n:>8} {snr:>5.1f}   not tuned: {first}")
                    hier_rows.append({"n": n, "snr": snr, "fd": a.fd,
                                      "data": a.data, "templates": a.templates,
                                      "uncovered": first})
                    continue
                tag = "%d/%d/%d" % cfg
                print(f"  {n:>8} {snr:>5.1f} {tf * 1e3:>10.2f}ms "
                      f"{th * 1e3:>10.2f}ms {speed:>8.2f}x {rate:>9.1%} "
                      f"{tag:>14}")
                hier_rows.append({"n": n, "snr": snr, "fd": a.fd,
                                  "data": a.data, "templates": a.templates,
                                  "flat_ms": tf * 1e3, "hier_ms": th * 1e3,
                                  "speedup": speed, "refine_rate": rate,
                                  "band": cfg[0], "oversample": cfg[1],
                                  "taps": cfg[2]})
        print("\nThe margin skips a pair when a cheap low-band estimate rules out\n"
              "any sample reaching the threshold, so the speedup grows with the\n"
              "threshold and falls to ~1 on data where everything triggers.\n"
              "'chosen' is the first-stage band/oversample/taps the library\n"
              "selected from the reference and the threshold -- not a setting\n"
              "of this benchmark. It should narrow as the threshold rises.")

    if a.json:
        with open(a.json, "w") as fh:
            json.dump({"host": host_info(a.label),
                       "flat": flat_rows, "hierarchical": hier_rows}, fh, indent=1)
        print(f"\nwrote {a.json}")

    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
