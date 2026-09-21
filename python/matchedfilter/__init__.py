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
           "__version__"]


def backend():
    """Name of the kernel the dispatcher selected for this CPU.

    Which one runs depends on the host, so a benchmark number is not
    interpretable without it.  Override with the ``MF_ISA`` environment
    variable to force a narrower one (``avx2``) and compare.
    """
    return _core.backend()


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
        self._mf = _core.MF(self.n, self.ndata, self.ntemplates)

    # ---- ingest -------------------------------------------------------------
    def set_data(self, spectra, index=None):
        """Set one data spectrum (with ``index``) or all from a (ndata, n) array.

        Inputs are frequency domain - the unnormalised forward transform of the
        segment, natural order.
        """
        if index is not None:
            self._mf.set_data(int(index), _as_c64(spectra, self.n, "spectrum"))
            return
        a = np.ascontiguousarray(spectra, dtype=np.complex64)
        if a.ndim != 2 or a.shape != (self.ndata, self.n):
            raise ValueError(f"expected shape ({self.ndata}, {self.n}), got {a.shape}")
        for i in range(self.ndata):
            self._mf.set_data(i, a[i])

    def set_templates(self, spectra, index=None):
        """Set one template spectrum (with ``index``) or all from a (ntemplates, n) array.

        Conjugation happens here, once, rather than in the pair loop.
        """
        if index is not None:
            self._mf.set_template(int(index), _as_c64(spectra, self.n, "spectrum"))
            return
        a = np.ascontiguousarray(spectra, dtype=np.complex64)
        if a.ndim != 2 or a.shape != (self.ntemplates, self.n):
            raise ValueError(f"expected shape ({self.ntemplates}, {self.n}), got {a.shape}")
        for i in range(self.ntemplates):
            self._mf.set_template(i, a[i])

    # ---- run ----------------------------------------------------------------
    def nbins(self, binsize, window=None):
        start, end = self._window(window)
        return self._mf.nbins(int(binsize), start, end)

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
        nb = self._mf.nbins(binsize, start, end)
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
        self._mf.run(d0, nd, t0, nt, binsize, float(threshold), start, end,
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
        >>> hf.trigger_rate        # fraction of pairs that needed the full filter

    The guarantee is one-sided and exact.  Every peak it reports is
    bit-identical to :class:`MatchedFilter`'s, because when the gate fires it
    runs that filter.  It never invents a peak and never shifts one.  What it can
    do is MISS one, with probability at most ``fd`` for a signal of strength
    ``snr``.  If that is not acceptable, use :class:`MatchedFilter`.

    ``snr`` is the |rho| of the weakest signal that must be kept; ``fd`` is the
    tolerated false-dismissal probability for such a signal.  Lowering either
    costs speed, because the gate has to open wider.  Band, oversampling and tap
    count come from a compiled-in measured table - matchedfilter does not autotune -
    and can be pinned with ``band`` / ``oversample`` / ``taps`` for testing.
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
        if band is None:
            self._mf = _core.HMF(self.n, self.ndata, self.ntemplates, self.snr, self.fd)
        else:
            self._mf = _core.HMF(self.n, self.ndata, self.ntemplates, self.snr, self.fd,
                                 int(band), int(oversample or 2), int(taps or 8))

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
        the gate would read the filter, not the signal.

        The output distribution is a property of the signal rather than of any
        one template and is near-identical across a bank, so set it once here
        rather than tuning per template.  Doing so also skips the per-template
        ingest measurement.  Pass ``None`` to go back to measuring each
        template.
        """
        if power is None:
            self._mf.set_reference(None)
            return
        p = np.ascontiguousarray(power, dtype=np.float32)
        if p.size != self.n:
            raise ValueError(f"reference must have {self.n} values, got {p.size}")
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
        nb = self._mf.nbins(binsize, int(ws[0]), int(we[0]))
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
        self._mf.run_series(ser, st, ws, we, t0, nt, binsize, float(threshold),
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
        band, u, k = self._mf.config()
        return band, u, k

    @property
    def stats(self):
        """``(pairs, triggers)`` accumulated since construction."""
        return self._mf.stats()

    @property
    def trigger_rate(self):
        """Fraction of pairs that needed the full correlation.

        This is what the speedup rides on, and the first thing to look at when
        the filter is slower than expected: a data set noisier than the design
        assumed opens the gate more often, and at a high enough trigger rate the
        coarse pass is pure overhead.
        """
        pairs, trig = self._mf.stats()
        return trig / pairs if pairs else 0.0
