"""apogee - single-threaded batched matched filter with peak-only output.

Correlate D data segments against T templates and report, for each pair, the
loudest sample in each bin of a search window:

    >>> import numpy as np, apogee
    >>> mf = apogee.MatchedFilter(1 << 14, ndata=16, ntemplates=16)
    >>> mf.set_data(data_spectra)         # (16, 16384) complex64, ALREADY FFT'd
    >>> mf.set_templates(template_spectra)
    >>> peaks = mf.run(binsize=1024, threshold=t, window=(a, b))
    >>> peaks["index"], peaks["value"], peaks["magnitude"]

Produce the spectra with whatever you already use - numpy, MKL, FFTW.  apogee
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

#: dtype of the arrays returned by :meth:`MatchedFilter.run`.
PEAK_DTYPE = np.dtype([("index", "<i8"), ("value", "<c8"), ("magnitude", "<f4")])

__all__ = ["MatchedFilter", "PEAK_DTYPE"]


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
            data=None, templates=None, counts=False):
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
        idx = np.empty(rows * nb, dtype=np.int64)
        val = np.empty(rows * nb, dtype=np.complex64)
        mag = np.empty(rows * nb, dtype=np.float32)
        cnt = np.empty(rows, dtype=np.int32)
        self._mf.run(d0, nd, t0, nt, binsize, float(threshold), start, end,
                     idx, val, mag, cnt)
        peaks = np.empty((nd, nt, nb), dtype=PEAK_DTYPE)
        peaks["index"] = idx.reshape(nd, nt, nb)
        peaks["value"] = val.reshape(nd, nt, nb)
        peaks["magnitude"] = mag.reshape(nd, nt, nb)
        return (peaks, cnt.reshape(nd, nt)) if counts else peaks


