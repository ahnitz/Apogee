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

__all__ = ["Plan", "fft", "topk", "topk_many", "FORWARD", "BACKWARD", "MAX_K", "PEAK_DTYPE"]


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

    def topk(self, x, k=1, direction=FORWARD, window=None):
        """The ``k`` loudest bins, ordered loudest first.

        Returns a structured array with fields ``index`` (int64), ``value``
        (complex64) and ``magnitude`` (float32), so both the location and the
        value of each peak are explicit.  The full spectrum is never formed.

        ``window=(start, end)`` restricts the search to ``start <= k < end``.
        Reported indices stay absolute.  Bins outside the window are never
        tested, so a narrower window is slightly cheaper; the transform itself
        costs the same either way.
        """
        x = self._check(x)
        k = int(k)
        if window is None:
            ws, we = 0, self.n
        else:
            ws, we = int(window[0]), int(window[1])
            ws = max(0, min(ws, self.n))
            we = max(0, min(we, self.n))
        idx = np.empty(max(k, 1), dtype=np.int64)
        val = np.empty(max(k, 1), dtype=np.complex64)
        mag = np.empty(max(k, 1), dtype=np.float32)
        n = _core.topk(self._p, x, k, idx, val, mag, _sign(direction), ws, we)
        peaks = np.empty(n, dtype=PEAK_DTYPE)
        peaks["index"] = idx[:n]
        peaks["value"] = val[:n]
        peaks["magnitude"] = mag[:n]
        return peaks


    def topk_many(self, x, k=1, threshold=0.0, direction=FORWARD, window=None):
        """Batched :meth:`topk`.

        ``x`` is a 2-D array of shape ``(b, n)`` - one transform per row.  Each
        transform keeps its own cache-resident working set, so this is a batch of
        separate transforms rather than an interleave.

        ``threshold`` is a magnitude floor, combined with ``k``: the result is the
        ``k`` loudest bins that are also above the floor.  A non-zero floor is
        also faster, because it primes the candidate test rather than filtering
        after the fact - at ``k=64`` that is worth about 10x at n=1024.

        Returns a list of ``b`` structured arrays, one per row, each ordered
        loudest first.  A row may be shorter than ``k`` when the floor cuts it.
        """
        x = np.ascontiguousarray(x, dtype=np.complex64)
        if x.ndim != 2 or x.shape[1] != self.n:
            raise ValueError(f"expected a 2-D array of shape (b, {self.n}), got {x.shape}")
        b = x.shape[0]
        k = int(k)
        if window is None:
            ws, we = 0, self.n
        else:
            ws, we = int(window[0]), int(window[1])
            ws = max(0, min(ws, self.n))
            we = max(0, min(we, self.n))
        idx = np.empty(b * max(k, 1), dtype=np.int64)
        val = np.empty(b * max(k, 1), dtype=np.complex64)
        mag = np.empty(b * max(k, 1), dtype=np.float32)
        cnt = np.empty(b, dtype=np.int32)
        _core.topk_many(self._p, x, self.n, b, k, float(threshold),
                        idx, val, mag, cnt, _sign(direction), ws, we)
        out = []
        for j in range(b):
            m = int(cnt[j])
            peaks = np.empty(m, dtype=PEAK_DTYPE)
            sl = slice(j * k, j * k + m)
            peaks["index"] = idx[sl]
            peaks["value"] = val[sl]
            peaks["magnitude"] = mag[sl]
            out.append(peaks)
        return out


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


def topk(x, k=1, direction=FORWARD, window=None):
    """One-shot :meth:`Plan.topk`, caching the plan by length."""
    x = np.ascontiguousarray(x, dtype=np.complex64)
    return _plan(x.size).topk(x, k, direction, window)


def topk_many(x, k=1, threshold=0.0, direction=FORWARD, window=None):
    """One-shot :meth:`Plan.topk_many`, caching the plan by row length."""
    x = np.ascontiguousarray(x, dtype=np.complex64)
    if x.ndim != 2:
        raise ValueError(f"expected a 2-D array of shape (b, n), got {x.shape}")
    return _plan(x.shape[1]).topk_many(x, k, threshold, direction, window)
