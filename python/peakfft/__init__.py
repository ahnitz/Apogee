"""peakfft - single-threaded AVX-512 FFT specialised for finding the loudest bins.

    >>> import numpy as np, peakfft
    >>> x = (np.random.randn(1 << 20) + 1j*np.random.randn(1 << 20)).astype(np.complex64)
    >>> peaks = peakfft.topk(x, 3)
    >>> peaks["index"], peaks["value"], peaks["magnitude"]

Supported lengths are 1024 and the powers of two from 4096 to 1048576.
"""
import numpy as np
from . import _core

FORWARD = _core.FORWARD
BACKWARD = _core.BACKWARD
MAX_K = _core.MAX_K

#: dtype of the array returned by :func:`topk` - index, complex value, magnitude.
PEAK_DTYPE = np.dtype([("index", "<i8"), ("value", "<c8"), ("magnitude", "<f4")])

__all__ = ["Plan", "fft", "topk", "FORWARD", "BACKWARD", "MAX_K", "PEAK_DTYPE"]


def _sign(direction):
    if isinstance(direction, str):
        d = direction.lower()
        if d in ("forward", "fwd", "f", "-1"):
            return FORWARD
        if d in ("backward", "bwd", "b", "inverse", "inv", "+1", "1"):
            return BACKWARD
        raise ValueError(f"unknown direction {direction!r}")
    if direction not in (FORWARD, BACKWARD):
        raise ValueError("direction must be FORWARD (-1) or BACKWARD (+1)")
    return int(direction)


class Plan:
    """Reusable plan for one transform length.  Serves both directions.

    Creating a plan builds the twiddle tables and scratch buffers, so reuse it
    across calls; that is where the setup cost belongs.
    """

    def __init__(self, n):
        self._p = _core.Plan(int(n))
        self.n = int(n)

    def _check(self, x):
        x = np.ascontiguousarray(x, dtype=np.complex64)
        if x.ndim != 1 or x.size != self.n:
            raise ValueError(f"expected a 1-D array of {self.n} samples, got shape {x.shape}")
        return x

    def fft(self, x, direction=FORWARD, out=None):
        """Full transform.  Returns a complex64 array of length n.

        No 1/n scaling is applied in either direction, matching FFTW and MKL, so
        ``plan.fft(plan.fft(x), BACKWARD)`` returns ``n * x``.
        """
        x = self._check(x)
        if out is None:
            out = np.empty(self.n, dtype=np.complex64)
        elif out.dtype != np.complex64 or out.size != self.n or not out.flags.c_contiguous:
            raise ValueError("out must be a contiguous complex64 array of length n")
        _core.fft(self._p, x, out, _sign(direction))
        return out

    def topk(self, x, k=1, direction=FORWARD):
        """The ``k`` loudest bins, ordered loudest first.

        Returns a structured array with fields ``index`` (int64), ``value``
        (complex64) and ``magnitude`` (float32), so both the location and the
        value of each peak are explicit.  The full spectrum is never formed.
        """
        x = self._check(x)
        k = int(k)
        idx = np.empty(max(k, 1), dtype=np.int64)
        val = np.empty(max(k, 1), dtype=np.complex64)
        mag = np.empty(max(k, 1), dtype=np.float32)
        n = _core.topk(self._p, x, k, idx, val, mag, _sign(direction))
        peaks = np.empty(n, dtype=PEAK_DTYPE)
        peaks["index"] = idx[:n]
        peaks["value"] = val[:n]
        peaks["magnitude"] = mag[:n]
        return peaks


_cache = {}


def _plan(n):
    p = _cache.get(n)
    if p is None:
        p = _cache[n] = Plan(n)
    return p


def fft(x, direction=FORWARD, out=None):
    """One-shot :meth:`Plan.fft`, caching the plan by length."""
    x = np.ascontiguousarray(x, dtype=np.complex64)
    return _plan(x.size).fft(x, direction, out)


def topk(x, k=1, direction=FORWARD):
    """One-shot :meth:`Plan.topk`, caching the plan by length."""
    x = np.ascontiguousarray(x, dtype=np.complex64)
    return _plan(x.size).topk(x, k, direction)
