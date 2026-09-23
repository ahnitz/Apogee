"""matchedfilter - single-threaded batched matched filter with peak-only output.

Correlate D data segments against T templates and report, for each pair, the
loudest sample in each bin of a search window:

    >>> import matchedfilter as mf
    >>> filt = mf.MatchedFilter(1 << 14, ndata=16, ntemplates=16)
    >>> filt.set_data(data_spectra)       # (16, 16384) complex64, ALREADY FFT'd
    >>> filt.set_templates(template_spectra)
    >>> peaks = filt.run(binsize=1024, threshold=t, window=(a, b))
    >>> peaks["index"], peaks["value"], peaks["magnitude"]

Produce the spectra with whatever you already use - numpy, MKL, FFTW.  matchedfilter
does not need to own that step, and there is no plan object to manage: the
MatchedFilter is built once and reused for every pair.

Inputs are FREQUENCY-DOMAIN: the unnormalised forward transform of each segment,
in natural order.  Ingest only rearranges - templates are conjugated and both
sides are stored in the layout the correlation loop walks - which measures at
2-4% of total and shrinks as the number of templates grows.

Supported lengths are 1024 and the powers of two from 4096 to 1048576.
"""
import math
import os
import warnings

import numpy as np
from . import _core

try:
    from importlib.metadata import version as _version, PackageNotFoundError
    __version__ = _version("matchedfilter")
except (ImportError, PackageNotFoundError):  # running from a source tree
    __version__ = "0.0.0.dev0"

#: dtype of the arrays returned by :meth:`MatchedFilter.run`.
PEAK_DTYPE = np.dtype([("index", "<i8"), ("value", "<c8"), ("magnitude", "<f4")])

__all__ = ["MatchedFilter", "HierarchicalFilter", "PEAK_DTYPE", "backend",
           "targets", "set_target", "__version__"]


def backend():
    """Name of the SIMD target selected for this CPU, e.g. ``"AVX2"``.

    Which one runs depends on the host, so a benchmark number is not
    interpretable without it.  ``MF_ISA`` forces one from the environment and
    :func:`set_target` does the same inside a running process.
    """
    return _core.backend()


def targets():
    """SIMD targets this build contains that this CPU can run, widest first.

    What a build contains is decided by the compiler, not by matchedfilter, so
    this is the only reliable list -- a machine without AVX-512 will not
    report ``AVX3`` however the wheel was built.
    """
    return _core.targets()


def set_target(name):
    """Narrow the choice to one target, or restore the default with ``None``.

    For comparing targets in one process.  Plans already created keep the
    kernel they were built with, so create the plan after setting this.
    """
    _core.set_target(name)


def _as_c64(a, n, what):
    a = np.ascontiguousarray(a, dtype=np.complex64)
    if a.ndim != 1 or a.size != n:
        raise ValueError(f"{what} must be a 1-D complex array of {n} samples, got shape {a.shape}")
    return a


class MatchedFilter:
    """Correlate a set of data segments against a set of templates.

    Inputs are the segments' spectra.  Every pair (d, t) gives
    ``IFFT(data_d * conj(template_t))``, of which only the loudest sample per bin
    is reported.  The transform is unnormalised, matching FFTW and MKL, so a perfect
    match returns ``n * energy``.

    ``ndata`` and ``ntemplates`` are arbitrary; they need not match or be powers
    of two.  Setting a segment transforms it once and stores it in the layout the
    correlation loop wants, so that cost is paid once rather than per pair.
    """

    def __init__(self, n, ndata=1, ntemplates=1):
        self.n = int(n)
        self.ndata = int(ndata)
        self.ntemplates = int(ntemplates)
        self._buf = None
        # Arrays the plan holds pointers into. The C side keeps the caller's
        # spectrum rather than copying it, so the wrapper must keep it alive.
        self._held = {}
        self._mf = _core.MF(self.n, self.ndata, self.ntemplates)

    # ---- ingest -------------------------------------------------------------
    def _ensure(self):
        """The live plan. Always built here; HierarchicalFilter defers."""
        return self._mf

    def set_data(self, spectra, index=None):
        """Set one data spectrum (with ``index``) or all from a (ndata, n) array.

        Inputs are frequency domain - the unnormalised forward transform of the
        segment, natural order.
        """
        if index is not None:
            a = _as_c64(spectra, self.n, "spectrum")
            # The plan keeps this pointer -- the coarse band is read straight
            # out of it during run(), and the full spectrum is ingested lazily
            # only if a pair fires. A caller passing a temporary would have it
            # freed before either happens, which is a use-after-free that only
            # shows when the refine path runs. Hold a reference.
            self._held[int(index)] = a
            self._ensure().set_data(int(index), a)
            return
        a = np.ascontiguousarray(spectra, dtype=np.complex64)
        if a.ndim != 2 or a.shape != (self.ndata, self.n):
            raise ValueError(f"expected shape ({self.ndata}, {self.n}), got {a.shape}")
        self._held[-1] = a                      # see the note above
        for i in range(self.ndata):
            self._ensure().set_data(i, a[i])

    def set_templates(self, spectra, index=None):
        """Set one template spectrum (with ``index``) or all from a (ntemplates, n) array.

        Conjugation happens here, once, rather than in the pair loop.
        """
        if index is not None:
            self._ensure().set_template(int(index), _as_c64(spectra, self.n, "spectrum"))
            return
        a = np.ascontiguousarray(spectra, dtype=np.complex64)
        if a.ndim != 2 or a.shape != (self.ntemplates, self.n):
            raise ValueError(f"expected shape ({self.ntemplates}, {self.n}), got {a.shape}")
        for i in range(self.ntemplates):
            self._ensure().set_template(i, a[i])

    # ---- run ----------------------------------------------------------------
    def nbins(self, binsize, window=None):
        start, end = self._window(window)
        return self._ensure().nbins(int(binsize), start, end)

    def _window(self, window):
        if window is None:
            return 0, self.n
        start, end = int(window[0]), int(window[1])
        start = max(0, min(start, self.n))
        end = max(0, min(end, self.n))
        if start >= end:
            raise ValueError(f"empty window ({start}, {end})")
        return start, end

    def run(self, binsize=None, threshold=0.0, window=None,
            data=None, templates=None, counts=False, raw=False):
        """Correlate and report the loudest sample per bin.

        Returns a structured array of shape ``(ndata, ntemplates, nbins)`` with
        fields ``index`` (lag, int64), ``value`` (complex64) and ``magnitude``
        (float32).  A bin whose maximum does not exceed ``threshold`` comes back
        with ``index == -1`` and ``magnitude == 0``, so bin j always sits at
        slot j and the result can be indexed by frequency without searching.

        ``data`` and ``templates`` restrict the run to a sub-range, given as
        ``(start, count)``; the answer is identical to the matching slice of a
        full run.  ``window=(start, end)`` restricts the lags searched.

        With ``counts=True`` returns ``(peaks, counts)``, where counts has shape
        ``(ndata, ntemplates)`` and holds how many bins crossed the threshold.

        ``raw=True`` returns ``(index, value, magnitude)`` as three plain arrays
        of shape ``(ndata, ntemplates, nbins)`` instead of assembling a
        structured array.  A caller driving small batches in a tight loop pays
        for that assembly on every call -- three field copies here and a
        structured-array slice at the other end -- which can exceed the filter
        work itself.  The arrays are views on buffers reused between calls, so
        copy anything that must outlive the next ``run``.
        """
        n = self.n
        binsize = n if binsize is None else int(binsize)
        start, end = self._window(window)
        d0, nd = (0, self.ndata) if data is None else (int(data[0]), int(data[1]))
        t0, nt = (0, self.ntemplates) if templates is None else (int(templates[0]), int(templates[1]))
        if nd < 1 or nt < 1 or d0 < 0 or t0 < 0 \
           or d0 + nd > self.ndata or t0 + nt > self.ntemplates:
            raise ValueError("data/templates sub-range out of bounds")
        nb = self._ensure().nbins(binsize, start, end)
        rows = nd * nt
        # Reuse the output buffers.  Six allocations per call is nothing beside
        # a 2^20 transform, but a caller driving small batches in a tight loop
        # pays it every time: at 37 templates it was 15 of the 21 us a call
        # took, swamping the work itself.
        buf = self._buf
        if buf is None or buf[0] != (rows, nb):
            idx = np.empty(rows * nb, dtype=np.int64)
            val = np.empty(rows * nb, dtype=np.complex64)
            mag = np.empty(rows * nb, dtype=np.float32)
            cnt = np.empty(rows, dtype=np.int32)
            peaks = np.empty((nd, nt, nb), dtype=PEAK_DTYPE)
            buf = self._buf = ((rows, nb), idx, val, mag, cnt, peaks)
        _, idx, val, mag, cnt, peaks = buf
        self._ensure().run(d0, nd, t0, nt, binsize, float(threshold), start, end,
                     idx, val, mag, cnt)
        if raw:
            r = (idx.reshape(nd, nt, nb), val.reshape(nd, nt, nb),
                 mag.reshape(nd, nt, nb))
            return (r, cnt.reshape(nd, nt)) if counts else r
        peaks["index"] = idx.reshape(nd, nt, nb)
        peaks["value"] = val.reshape(nd, nt, nb)
        peaks["magnitude"] = mag.reshape(nd, nt, nb)
        return (peaks, cnt.reshape(nd, nt)) if counts else peaks




def include_dir():
    """Directory holding matchedfilter.h, for building C code against this package.

    Direct C use is not the main path - the Python class is - but linking is
    cheap to support::

        cc myprog.c $(python -c "import matchedfilter; print('-I'+matchedfilter.include_dir())") ...

    The C interface is the same ten functions the class wraps; see matchedfilter.h.
    """
    import os
    return os.path.dirname(os.path.abspath(__file__))



_TUNING = None
_warned_uncovered = False


def _uncovered_message(n, snr, fd):
    """Why autotuning refused, and what to do about it.

    Only the DISCRETE choices are limited by these tables. The coarse
    threshold itself is interpolated in (f_eff, snr) by src/hmf_table.h over
    snr 4.5 to 8.0 and clamps conservatively outside, so the threshold adapts
    to any request; what is missing here is measured evidence for which band,
    oversampling, taps and margin to pair it with.
    """
    t = _load_tuning()
    ns = sorted({r[0] for r in t["fdr"]})
    snrs = _complete_snrs(t, n)
    floor = _dismissal_floor(t)
    if not snrs:
        where = "n=%d is not in the tables" % n
    elif fd < floor:
        # The commonest reason, and the one the old message mis-attributed to
        # the threshold: the budget is below what the trial count can resolve.
        # Saying "not measured at this threshold" there sends the reader to
        # the wrong axis entirely.
        where = ("fd=%.0e is below the %.1e this table can resolve -- it was "
                 "measured at %s trials a cell, and a rate under about "
                 "3/trials is a floor rather than a result" % (fd, floor,
                 t["meta"].get("trials", "an unrecorded number of")))
    elif snr < min(snrs):
        where = "snr %.2f is below the lowest measured, %g" % (snr, min(snrs))
    elif snr > max(snrs):
        where = "snr %.2f is above the highest measured, %g" % (snr, max(snrs))
    else:
        where = ("no measured configuration at snr %.2f meets fd=%.0e" 
                 % (snr, fd))
    return ("no measured tuning for n=%d snr=%.2f fd=%.0e -- %s. The tables "
            "cover n=%s, snr=%s, and a threshold ABOVE that range is answered "
            "conservatively; below or between it is not, because a lower "
            "threshold is a harder problem and nothing measured bounds it. "
            "Either pass band/oversample/taps explicitly, or generate "
            "coverage with tools/hmf_tune.py and point MF_ACCURACY and "
            "MF_COST at it. See docs/hierarchical.md."
            % (n, snr, fd, where, ns, snrs or "none at this n"))


def _load_tuning(path=None):
    """Read the tuning table: measured dismissal and cost per configuration.

    Shipped as package data and overridable with MF_TUNING or the `tuning`
    argument, so a user can retune for their own CPU without rebuilding --
    which they will need to, since the COST rows are measurements of one
    machine and the FDR rows of one build.  Read once and cached; the lookup
    is a handful of sums over the reference, so it costs nothing against a
    plan that then filters millions of pairs.
    """
    global _TUNING
    if _TUNING is not None and path is None:
        return _TUNING
    here = os.path.dirname(__file__)
    paths = [os.environ.get("MF_ACCURACY") or os.path.join(here, "accuracy.txt"),
             os.environ.get("MF_COST") or os.path.join(here, "cost.txt")]
    if path is not None:
        paths = [path]
    fdr, cost, meta = [], {}, {}
    for one in paths:
      with open(one) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("#"):
                bits = line[1:].split(None, 1)
                if len(bits) == 2 and bits[0] in ("cpu", "commit", "trials"):
                    meta[bits[0]] = bits[1]
                continue
            if not line:
                continue
            f = line.split()
            if f[0] in ("FDR", "ACC"):
                fdr.append((int(f[1]), int(f[2]), int(f[3]), int(f[4]),
                            float(f[5]), float(f[6]), float(f[7]),
                            float(f[8]), float(f[9])))
            elif f[0] == "COST":
                cost.setdefault((int(f[1]), int(f[2]), int(f[3]), int(f[4]),
                                 float(f[5]), float(f[8])), []).append(
                                     (float(f[6]), float(f[7]), float(f[9])))
    # Index the accuracy rows by (n, snr) once, here, instead of scanning all
    # of them on every selection. choose_config used to walk the whole list,
    # which cost 4.9 ms once the tables covered eight transform lengths.
    # 4.9 ms -> 0.22 ms.
    #
    # This is NOT what made pycbc_inspiral_fir look 28% slower, though the
    # commit that introduced it said so. Plans are cached by (nbatch, ndata)
    # and that run builds one, so selection happens ONCE, not once per
    # segment; the 64 ms figure came from multiplying by a segment count
    # without checking. Per-segment timings put the whole difference in the
    # first segment -- 48 ms against 15 ms, with every steady-state segment
    # identical at 7.0 ms -- and that is _load_tuning below, parsing tables
    # that grew from 1920 rows to over 30000. Fixed 50 ms of startup, not a
    # throughput cost: +55% on a 13-segment smoke test, +0.7% at 1000.
    #
    # Two attempts to speed the parse up both made it slower (np.array on
    # split rows 74 ms, np.fromstring 64 ms, against 50). The cost is building
    # 11264 tuples and 2048 dict entries in Python, not converting floats, so
    # parsing in C and handing the result back through tolist() moves the work
    # rather than removing it. Recorded so the next attempt starts elsewhere.
    by_ns = {}
    for r in fdr:
        by_ns.setdefault((r[0], r[4]), []).append(r)
    snrs_at = {}
    for (rn, rs) in by_ns:
        snrs_at.setdefault(rn, []).append(rs)
    for rn in snrs_at:
        snrs_at[rn] = sorted(snrs_at[rn])
    cost_cfg = {}
    for (kn, kb, kU, kK, s, km) in cost:
        cost_cfg.setdefault((kn, kb, kU, kK, km), []).append(s)
    t = {"fdr": fdr, "cost": cost, "meta": meta, "paths": paths,
         "by_ns": by_ns, "snrs_at": snrs_at,
         "cost_cfg": {k: sorted(v) for k, v in cost_cfg.items()}}
    if path is None or _TUNING is None:
        _TUNING = t
    return t


def _band_features(power, m):
    """(in-band fraction, effective bandwidth in bins) at band m.

    These two determine the statistic: the fraction says how much signal the
    band keeps, the bandwidth how sharp the resulting correlation peak is --
    and the peak's width against the lag spacing is what the coarse threshold has to
    survive.  Both come straight from the reference.
    """
    p = np.asarray(power, dtype=np.float64)
    p = np.where(p > 0, p, 0.0)
    tot = p.sum()
    if tot <= 0:
        return 0.0, 1.0
    inb = p[:m]
    s = inb.sum()
    if s <= 0:
        return 0.0, 1.0
    q = inb / s
    return float(s / tot), float(1.0 / np.sum(q ** 2))


def _cost_snrs(t, n, band, U, K, margin, want):
    """Which cost rows to price a configuration with.

    The two tables are allowed to disagree about coverage -- accuracy is a
    property of the algorithm and cost of the machine, so they are regenerated
    independently and one can be ahead of the other. Requiring the cost row at
    exactly the accuracy row's threshold coupled them, and the moment accuracy
    gained snr 6.5 at n=4096 before cost did, every candidate was rejected for
    want of a price and autotuning refused outright.

    Cost cannot break the budget -- it only ranks configurations that accuracy
    has already admitted -- so it falls back to the nearest measured threshold
    rather than refusing. A slightly mispriced ranking is a performance
    question; no answer at all is a correctness one.
    """
    have = t["cost_cfg"].get((n, band, U, K, margin), ())
    if not have:
        return ()
    exact = [w for w in want if any(abs(w - h) < 1e-9 for h in have)]
    if exact:
        return tuple(exact)
    return (min(have, key=lambda h: abs(h - max(want))),)


def _margin_at_budget(curve, fd, floor):
    """Largest coarse margin whose interpolated dismissal still meets `fd`.

    The margin is a continuous scale on the coarse threshold, but it was only
    ever measured at four points and selection snapped to them. At n=4096,
    snr 5.5, band 512 the grid lands on 0.90, whose measured dismissal is
    1.5e-4 against a 1e-3 budget -- seven times safer than asked, and that
    safety is not free: 0.90 escalates 19.1% of pairs where the interpolated
    0.924 escalates 12.1%, measuring 1.95x against 2.44x.

    Dismissal rises steeply and smoothly with the margin, so it is
    interpolated in LOG dismissal, which is near-linear in the margin over a
    grid step where the raw value moves by more than an order of magnitude.

    `floor` is the trials resolution. A measured 0.0 does not mean zero, it
    means "not resolved", so it is read as the floor rather than as -inf --
    otherwise a single unresolved cell would drag the interpolation to the
    grid edge and hand back exactly the over-safe snap this removes.

    Returns None if even the tightest measured margin misses the budget.
    """
    pts = sorted(curve)
    ms = [m for m, _ in pts]
    ds = [max(d, floor) for _, d in pts]
    if ds[0] > fd:
        return None                       # tightest margin already over budget
    if ds[-1] <= fd:
        return ms[-1]                     # every margin fits; take the loosest
    y = [math.log10(d) for d in ds]
    t = math.log10(fd)
    for i in range(len(ms) - 1):
        if y[i] <= t <= y[i + 1]:
            if y[i + 1] == y[i]:
                return ms[i + 1]
            w = (t - y[i]) / (y[i + 1] - y[i])
            return ms[i] + w * (ms[i + 1] - ms[i])
    return ms[0]


def _cost_at_margin(curve, margin):
    """Relative cost at a margin the table did not measure directly.

    Interpolated for the same reason the margin itself is: admitting a
    configuration at 0.924 and pricing it at 0.90 compares a cost the caller
    will never pay. Cost falls monotonically with the margin at every band --
    fewer escalations -- so linear interpolation between the bracketing grid
    points is well behaved. Clamped at the ends.
    """
    pts = sorted(curve)
    ms = [m for m, _ in pts]
    cs = [c for _, c in pts]
    if len(ms) == 1 or margin <= ms[0]:
        return cs[0]
    if margin >= ms[-1]:
        return cs[-1]
    for i in range(len(ms) - 1):
        if ms[i] <= margin <= ms[i + 1]:
            if ms[i + 1] == ms[i]:
                return cs[i]
            w = (margin - ms[i]) / (ms[i + 1] - ms[i])
            return cs[i] + w * (cs[i + 1] - cs[i])
    return cs[-1]


def _complete_snrs(t, n):
    """Measured thresholds at `n` whose band coverage is not a subset.

    Coverage grows by measurement, and a threshold measured for only some
    bands is a trap: it reads as an exact hit, so the conservative bracketing
    rule never engages, and the choice is quietly confined to the bands that
    happen to have rows.
    """
    bands = {}
    for s_ in t["snrs_at"].get(n, ()):
        bands[s_] = {r[1] for r in t["by_ns"].get((n, s_), ())}
    if not bands:
        return []
    full = max(len(v) for v in bands.values())
    return sorted(s_ for s_, v in bands.items() if len(v) == full)


def choose_config(power, n, snr, fd, tuning=None):
    """Cheapest (band, oversample, taps) whose measured dismissal meets `fd`.

    Each candidate is judged on the accumulation at its OWN band edge, since
    two references agreeing elsewhere disagree there.  The two features move
    the answer the same way -- measured, not assumed: at band 512 dismissal
    runs 2.9e-4 to 1.6e-2 as the in-band fraction goes 0.80 to 0.99, and
    2.9e-4 to 6.9e-3 as the effective bandwidth goes 10 bins to 463.  A higher
    fraction raises the coarse threshold; a broader in-band spread sharpens the peak the
    lag grid has to catch.  So the row that speaks for a reference is one
    measured at least as high in both, and the worst such row is the one to
    believe.

    Cost is RELATIVE, not microseconds, and that is what makes the ranking
    mean anything.  Each row was measured by holding one reference fixed and
    timing every configuration on it, so clock state, contention and the
    machine cancel in the ratio.  An earlier table timed each cell against its
    own synthetic reference, which meant band 512 and band 1024 were never
    compared on the same signal; it ranked the slowest of four admissible
    options first, 20.30 ms/segment where 13.29 was available.

    Ordering is what selection needs and ordering is what the table delivers:
    on the captures it reproduces the measured order of every candidate
    exactly.  Magnitudes are looser -- band 512 at a high in-band fraction
    comes out about 15% cheap -- so these numbers rank configurations and
    should not be read as predictions of runtime.

    The cheapest admissible configuration is not always the cheapest one that
    works on a given dataset: accuracy is judged against the table's measured
    dismissal rate, which resolves far below what any one dataset can show.

    Returns None when the table covers nothing that fits, which makes the
    caller refuse rather than guess -- there is no compiled fallback, by
    design: a model that does not promise the budget should not be allowed to
    answer in the budget's name.
    """
    t = _load_tuning() if tuning is None else tuning
    # Only thresholds whose band coverage matches the fullest available at
    # this length. A partially measured threshold is worse than an absent one:
    # it looks like an exact hit, so the bracketing rule never fires, and
    # selection is silently restricted to whichever bands happen to have rows.
    # Adding snr 5.75 for newly measured bands alone did exactly that -- at
    # n=2048 it forced band 1024 where 5.5 and 6.0 both choose 512, and the
    # speedup fell from 3.60x to 2.07x.
    tsnrs = _complete_snrs(t, n)
    if not tsnrs:
        return None
    use, why = _snr_rows_for(snr, tsnrs)
    if use is None:
        return None

    feats, byconf = {}, {}
    rows = [r for s_ in use for r in t["by_ns"].get((n, s_), ())]
    for (tn, band, U, K, tsnr, tf, tbe, margin, dm) in rows:
        if band >= n:
            continue
        if band not in feats:
            feats[band] = _band_features(power, band)
        byconf.setdefault((band, U, K, margin), []).append((tf, tbe, dm))
    # Group by (band, U, K) so the margin becomes a continuous axis within
    # each, rather than a fourth discrete choice snapped to four points.
    fam = {}
    for (band, U, K, margin), rows in byconf.items():
        fam.setdefault((band, U, K), {})[margin] = rows

    floor = _dismissal_floor(t)
    best, bcost, bmargin = None, float("inf"), None
    for (band, U, K), bymargin in fam.items():
        f, be = feats[band]
        dcurve, ccurve = [], []
        for margin, rows in bymargin.items():
            # clamp to the grid: past its edge the most pessimistic row is the
            # best evidence there is, and saying so beats extrapolating
            fq = min(f, max(r[0] for r in rows))
            bq = min(be, max(r[1] for r in rows))
            cover = [dm for (tf, tbe, dm) in rows
                     if tf >= fq - 1e-9 and tbe >= bq - 1e-9]
            if not cover:
                continue
            dcurve.append((margin, max(cover)))

            crows = []
            for cs in _cost_snrs(t, n, band, U, K, margin, use):
                crows += t["cost"].get((n, band, U, K, round(cs, 2), margin)) or []
            if not crows:
                continue
            # The accuracy rule's covering side, and it is the right one --
            # but not for the reason it was inherited.
            #
            # Cost and dismissal move OPPOSITE ways in f: more power in band
            # raises the coarse threshold, so fewer pairs escalate and the
            # configuration is cheaper, while dismissal rises. That argument
            # says this rule should under-price narrow bands, and it does.
            #
            # Three replacements were tried and MEASURED against the real best
            # of every admissible configuration, at four (n, snr) points:
            #
            #     rule                        4096@5.0 4096@6.0 8192@5.0 16384@5.5
            #     covering (this one)              80%      90%     100%      100%
            #     pessimistic (f <= ours)          80%      72%      45%       47%
            #     nearest in (f, beff)             63%      70%      57%       44%
            #     interpolate in f                 57%      83%      60%      100%
            #
            # The theory is right about the direction and wrong about what
            # follows from it: the rows are sparse and spread over B_eff as
            # well as f, and every alternative reasoning about f alone lands
            # on a row describing a different problem. Do not change this on
            # an argument -- re-run tools/score_cost_rule.py, because the
            # argument that looked conclusive cost up to 56% of the available
            # speedup when it was believed.
            cf = [c for (tf, tbe, c) in crows
                  if tf >= fq - 1e-9 and tbe >= bq - 1e-9]
            ccurve.append((margin,
                           max(cf) if cf else max(c for (_, _, c) in crows)))

        if not dcurve or not ccurve:
            continue
        margin = _margin_at_budget(dcurve, fd, floor)
        if margin is None:
            continue
        # Priced AT the margin that will actually be used. Admitting 0.924 and
        # pricing it at the 0.90 grid point compares a cost no caller pays,
        # and gets the ranking wrong: those two differ by 19.1% against 12.1%
        # escalation at n=4096 snr 5.5.
        c = _cost_at_margin(ccurve, margin)
        if c < bcost:
            best, bcost, bmargin = (band, U, K), c, margin
    if best is None:
        return None
    return (best[0], best[1], best[2], round(bmargin, 4))


def _dismissal_floor(t):
    """Smallest dismissal the shipped table could have resolved.

    A measured 0.0 means "not resolved at this trial count", not zero, and the
    margin interpolation has to read it that way or a single unresolved cell
    drags the answer to the grid edge.
    """
    try:
        return 3.0 / float(str(t["meta"].get("trials", "4000")).split()[0])
    except Exception:
        return 7.5e-4

    return best


def _snr_rows_for(snr, covered, tol=1e-6):
    """Which measured SNR rows speak for a threshold of `snr`.

    Exact hit: that row. Above everything measured: every covered row, and the
    worst dismissal among them -- because a threshold above the table is an
    EASIER problem and the measured range bounds it. Below the lowest measured
    row, or between two of them with neither covering: refuse.

    The asymmetry is deliberate and it is measured, not assumed. Dismissal is
    NOT monotone in the threshold -- 172 of 640 cells in the shipped table
    rise from snr 5.0 to 5.5 -- so "use the nearest lower row" would not be
    conservative and is not what this does. What was measured directly, at
    snr 6.5/7.0/8.0 across twelve configurations, is that nothing above the
    covered range exceeds its in-range maximum: the single apparent exception
    moved 5.6e-4 to 6.1e-4, one dismissal in 6000, at the resolution floor.
    So the bound that holds is the worst row anywhere in the measured range,
    and that is the one used.

    Below the range there is no such bound. A lower threshold is a harder
    problem and nothing measured speaks for it, so autotuning refuses rather
    than extrapolating a guarantee it cannot support.
    """
    if not covered:
        return None, "nothing measured"
    for c in covered:
        if abs(c - snr) <= tol:
            return (c,), "measured at snr %g" % c
    if snr < min(covered) - tol:
        return None, "below the lowest measured threshold, %g" % min(covered)
    if snr > max(covered) - tol:
        # Above everything measured. Use the HIGHEST measured row, not the
        # worst of all of them: a higher threshold is a strictly easier
        # problem, so the nearest measurement below it is the relevant one,
        # and taking the whole range's maximum imported snr 5.0's behaviour
        # into a case that is easier than snr 6.0. That cost real speed --
        # snr 6.5 was handed band 1024 where snr 6.0 got band 256, so asking
        # for a HIGHER threshold produced a SLOWER filter, which is backwards.
        hi = max(covered)
        return (hi,), "above the measured range; using the highest measured, snr %g" % hi
    lo = max(c for c in covered if c <= snr + tol)
    hi = min(c for c in covered if c >= snr - tol)
    # Strictly inside the range: bracketed, so the two neighbours bound it and
    # the worse of them is the honest answer. Dismissal is NOT monotone in the
    # threshold -- 172 of 640 fully-measured cells rise from snr 5.0 to 5.5 --
    # so the nearer neighbour alone would not be a bound.
    return (lo, hi), "between measured thresholds %g and %g" % (lo, hi)


class HierarchicalFilter(MatchedFilter):
    """Matched filter that correlates the low band first and refines on demand.

    Most of a template's SNR sits in the low part of its band.  This correlates
    only that part, on a coarse lag grid, and pays for the full correlation only
    where the coarse result could still become a detection.

        >>> hf = matchedfilter.HierarchicalFilter(1 << 12, ndata=16, ntemplates=16,
        ...                                snr=5.5, fd=1e-2)
        >>> hf.set_data(data_spectra)
        >>> hf.set_templates(template_spectra)
        >>> peaks = hf.run(binsize=1024, threshold=t)
        >>> hf.refine_rate        # fraction of pairs that needed the full filter

    The guarantee is one-sided and exact.  Every peak it reports is
    bit-identical to :class:`MatchedFilter`'s, because when the coarse pass escalates it
    runs that filter.  It never invents a peak and never shifts one.  What it can
    do is MISS one, with probability at most ``fd`` for a signal of strength
    ``snr``.  If that is not acceptable, use :class:`MatchedFilter`.

    ``snr`` is the |rho| of the weakest signal that must be kept; ``fd`` is the
    tolerated false-dismissal probability for such a signal.  Lowering either
    costs speed, because the coarse threshold has to open wider.  Band, oversampling and tap
    count come from a compiled-in measured table - matchedfilter does not tune the
    margin against your data - and can be pinned with ``band`` / ``oversample`` /
    ``taps`` for testing.  How the work is *arranged*, on the other hand, is
    chosen here and not by the caller: see :meth:`run_series`.
    """

    def __init__(self, n, ndata=1, ntemplates=1, snr=5.5, fd=1e-2,
                 band=None, oversample=None, taps=None):
        self.n = int(n)
        self.ndata = int(ndata)
        self.ntemplates = int(ntemplates)
        self.snr = float(snr)
        self.fd = float(fd)
        self._buf = None
        self._sbuf = None
        self._held = {}
        self._pending_ref = None
        if band is None:
            # Defer: the band should be chosen from the reference, and the
            # reference arrives after construction in every caller we have.
            # Building the plan on first use instead of here means the choice
            # can see it, with no rebuild and no re-ingest of templates.
            self._mf = None
            self._defer = True
        else:
            self._defer = False
            self._mf = _core.HMF(self.n, self.ndata, self.ntemplates, self.snr, self.fd,
                                 int(band), int(oversample or 2), int(taps or 8))

    def _ensure(self):
        """Build the plan, choosing its configuration if that was deferred.

        The band should be chosen from the reference, and every caller sets
        the reference after construction -- so the plan is built on first use
        instead of in __init__.  That lets the choice see the reference with
        no rebuild and no re-ingest of templates.
        """
        if self._mf is not None:
            return self._mf
        cfg = None
        if self._pending_ref is not None:
            try:
                cfg = choose_config(self._pending_ref, self.n, self.snr, self.fd)
            except Exception:
                cfg = None       # a missing or unreadable table is not fatal
        if cfg is None:
            # Autotuning is a promise, so it refuses rather than guesses.
            # There used to be a compiled design table to fall back on; it was
            # a model, it did not promise the budget -- 3.7% missed against
            # 0.1% on the captures -- and having it made the library quietly
            # answer a question it had no measurement for. A caller who wants
            # a configuration the tables do not cover states it directly.
            raise ValueError(_uncovered_message(self.n, self.snr, self.fd))
        b, u, k, margin = cfg
        self._mf = _core.HMF(self.n, self.ndata, self.ntemplates,
                             self.snr, self.fd, int(b), int(u), int(k))
        # the coarse threshold is the strongest lever and is tuned with the rest; it is
        # read per run, so setting it here is enough
        if abs(margin - 1.0) > 1e-9:
            self._mf.set_coarse_margin(float(margin))
        if self._pending_ref is not None:
            self._mf.set_reference(self._pending_ref)
        return self._mf

    def set_first_stage(self, snr):
        """Calibrate the first stage against `snr` rather than the threshold.

        Final triggers are still cut at the threshold passed to :meth:`run`;
        this sets only where the cheap first pass decides a full
        reconstruction is needed.  Lower it to run the first stage more
        conservatively, at the cost of reconstructing more often.

        The value chosen from ``snr`` and ``fd`` at construction is a
        suggestion, not a constraint -- it comes from an offline sweep whose
        recovery factors are measured against a mean spectrum, so it is not
        reliable everywhere (see docs/hierarchical.md).  Callers who know
        better should say so here.  Band, oversample and taps are fixed when
        the plan is built and are not affected.

        The design table's SNR grid starts at 4.5, and the level is
        interpolated on it, so anything lower **clamps to 4.5** rather than
        going further.  The call succeeds either way; if you need the first
        stage looser than that, widen the band instead.

        Pass ``None`` or a non-positive value to go back to deriving it.
        """
        self._ensure().set_first_stage(0.0 if snr is None else float(snr))

    def set_reference(self, power):
        """Set the reference SNR distribution.

        ``power`` is a real frequency series of length ``n``: the expected
        power of the filter *output* in each bin.  Only its shape matters, as
        the total is divided out.

        By default each template's band fraction and recovery factors are
        measured from the template itself, which assumes its own power
        distribution is the distribution of the SNR it produces.  That holds
        only when the data is white and the template whitened.  A broadband
        ratio filter reconstructing a low-frequency signal breaks it badly --
        the coarse threshold would read the filter, not the signal.

        The output distribution is a property of the signal rather than of any
        one template and is near-identical across a bank, so set it once here
        rather than tuning per template.  Doing so also skips the per-template
        ingest measurement.  Pass ``None`` to go back to measuring each
        template.
        """
        if power is None:
            self._pending_ref = None
            if self._mf is not None:
                self._mf.set_reference(None)
            return
        p = np.ascontiguousarray(power, dtype=np.float32)
        if p.size != self.n:
            raise ValueError(f"reference must have {self.n} values, got {p.size}")
        self._pending_ref = p
        if self._mf is not None:
            self._mf.set_reference(p)

    def run_series(self, series, starts, win_start, win_end,
                   binsize=None, threshold=0.0, templates=None, raw=False):
        """Filter a time series over a caller-supplied block layout.

        The caller keeps the overlap-save arithmetic -- where each block starts
        and which span of its output is valid.  matchedfilter only executes that plan,
        which removes the per-block round trip: no separately-planned forward
        FFT, no spectrum passed back and forth, and one call per segment rather
        than one per block.

        Windows are per block, so the ragged ones at a segment's edges need no
        grouping.  Returns a structured array of shape
        ``(nblocks, ntemplates, nbins)``, or with ``raw=True`` the three plain
        arrays ``(index, value, magnitude)`` of that shape -- which skips
        assembling the structured array, a real cost here because a whole
        segment's blocks come back at once.

        Give this as much of the series as is available.  Blocks are filtered
        several at a time, because D data segments against T templates is a
        symmetric product and one segment against a large bank is the worst
        shape to hand the kernel -- the bank gets streamed once per segment.
        The grouping is chosen internally from the transform length, breaks
        wherever consecutive blocks stop sharing a window, and cannot change
        any result; it is worth 1.17x at 418 templates and nothing at 37.
        Calling once per block, as an earlier version of the caller did,
        forfeits it.

        The returned arrays are the plan's own buffers and the next call
        overwrites them.  Copy anything that has to outlive the call.
        """
        ser = np.ascontiguousarray(series, dtype=np.complex64)
        st = np.ascontiguousarray(starts, dtype=np.uintp)
        ws = np.ascontiguousarray(win_start, dtype=np.uintp)
        we = np.ascontiguousarray(win_end, dtype=np.uintp)
        if not (st.size == ws.size == we.size):
            raise ValueError("starts, win_start and win_end must be the same length")
        nblk = st.size
        t0, nt = (0, self.ntemplates) if templates is None else (
            int(templates[0]), int(templates[1]))
        binsize = self.n if binsize is None else int(binsize)
        nb = self._ensure().nbins(binsize, int(ws[0]), int(we[0]))
        need = nblk * nt * nb
        # Reuse the buffers, as run() does.  Re-allocated per call they are a
        # small cost here -- one call per segment rather than per block -- but
        # the shape is stable across segments, so there is no reason to pay it.
        sb = self._sbuf
        if sb is None or sb[0] != (nblk, nt, nb):
            sb = self._sbuf = ((nblk, nt, nb),
                               np.empty(need, dtype=np.int64),
                               np.empty(need, dtype=np.complex64),
                               np.empty(need, dtype=np.float32),
                               np.empty(nblk * nt, dtype=np.int32))
        _, idx, val, mag, cnt = sb
        self._ensure().run_series(ser, st, ws, we, t0, nt, binsize, float(threshold),
                            idx, val, mag, cnt)
        if raw:
            return (idx.reshape(nblk, nt, nb), val.reshape(nblk, nt, nb),
                    mag.reshape(nblk, nt, nb))
        peaks = np.empty((nblk, nt, nb), dtype=PEAK_DTYPE)
        peaks["index"] = idx.reshape(nblk, nt, nb)
        peaks["value"] = val.reshape(nblk, nt, nb)
        peaks["magnitude"] = mag.reshape(nblk, nt, nb)
        return peaks

    @property
    def config(self):
        """``(band, oversample, taps)`` the design table selected."""
        band, u, k = self._ensure().config()
        return band, u, k

    @property
    def stats(self):
        """``(pairs, triggers)`` accumulated since construction."""
        return self._ensure().stats()

    @property
    def refine_rate(self):
        """Fraction of pairs that needed the full correlation.

        This is what the speedup rides on, and the first thing to look at when
        the filter is slower than expected: a data set noisier than the design
        assumed opens the coarse threshold more often, and at a high enough trigger rate the
        coarse pass is pure overhead.

        Counted over the plan's whole lifetime, not per run.  To measure one
        workload, filter it with a plan that has seen nothing else.
        """
        pairs, trig = self._ensure().stats()
        return trig / pairs if pairs else 0.0
