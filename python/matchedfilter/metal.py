"""The matched filter on the Apple GPU, through Metal.

Same inputs, outputs and semantics as :class:`matchedfilter.MatchedFilter`,
so either can be dropped in for the other::

    >>> from matchedfilter import metal
    >>> metal.available()
    True
    >>> filt = metal.MatchedFilter(1 << 14, ndata=16, ntemplates=64)
    >>> filt.set_data(data_spectra)          # (16, 16384) complex64, already FFT'd
    >>> filt.set_templates(template_spectra) # (64, 16384) complex64
    >>> peaks = filt.run(binsize=1024, threshold=5.5)

The kernels live in ``metal/`` at the top of the source tree and are separate
from the CPU code: the correlation product is formed inside the inverse
transform's first stage and the peak search runs on the transform's output in
threadgroup memory, so only the peaks are written back.  Lengths are the
powers of two from 256 to 2^21.

Values agree with the CPU filter to single precision, not bit for bit: the two
evaluate the same transform in different orders.  Where two lags in a bin are
tied to within rounding, the two back ends may report different ones.
"""
from . import MatchedFilter as _CPUMatchedFilter

try:
    from . import _metal
except ImportError:          # not macOS, or built with MF_NO_METAL
    _metal = None

__all__ = ["MatchedFilter", "available", "device"]


def available():
    """True if this build has the GPU back end and a Metal device to run it."""
    return _metal is not None and bool(_metal.available())


def device():
    """Name of the GPU the filter runs on, e.g. ``"Apple M2"``, or None."""
    return _metal.device() if _metal is not None else None


class MatchedFilter(_CPUMatchedFilter):
    """:class:`matchedfilter.MatchedFilter`, executed on the Apple GPU.

    Spectra are copied into GPU-visible memory at ingest (unified memory, so
    that is a plain copy, not a transfer), and every :meth:`run` is one
    command buffer: all ``ndata * ntemplates`` pairs are in flight at once.
    Give it as many pairs as you have -- a run of a handful of pairs is
    dominated by the fixed cost of submitting work to the GPU.
    """

    def __init__(self, n, ndata=1, ntemplates=1):
        if _metal is None:
            raise RuntimeError("matchedfilter was built without the Metal back end")
        self.n = int(n)
        self.ndata = int(ndata)
        self.ntemplates = int(ntemplates)
        self._buf = None
        self._held = {}
        self._mf = _metal.MF(self.n, self.ndata, self.ntemplates)

    @property
    def config(self):
        """The kernel shape chosen for this length, for reporting."""
        return self._mf.config()
