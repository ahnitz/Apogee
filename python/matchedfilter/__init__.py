"""matchedfilter - single-threaded batched matched filter with peak-only output.

Correlate D data segments against T templates and report, for each pair, the
loudest sample in each bin of a search window:

    >>> import matchedfilter as mf
    >>> filt = mf.MatchedFilter(1 << 14, ndata=16, ntemplates=16)
    >>> filt.set_data(data_spectra)       # (16, 16384) complex64, ALREADY FFT'd
    >>> filt.set_templates(template_spectra)
    >>> peaks = filt.run(binsize=1024, threshold=t, window=(a, b))
    >>> peaks["index"], peaks["value"]

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
#: A peak is WHERE and WHAT, nothing else. The magnitude used to be a third
#: field and was always abs(value) to the last bit, so it carried no
#: information -- it cost a field copy on assembly, a buffer, and on the GPU
#: a third output array and a sqrt per bin. Callers who want it write
#: np.abs(peaks["value"]).
PEAK_DTYPE = np.dtype([("index", "<i8"), ("value", "<c8")])

#: Transform lengths the GPU kernel covers. One workgroup carries a whole
#: transform, so 16384 is the ceiling at 1024 threads.
_GPU_SIZES = frozenset((1024, 2048, 4096, 8192, 16384))

__all__ = ["MatchedFilter", "HierarchicalFilter", "PEAK_DTYPE", "backend",
           "targets", "set_target", "devices", "Device", "__version__"]


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


#: DLPack device types we can read without a copy across a bus.
#: kDLCPU is 1; kDLCUDAHost (3) and kDLROCMHost (11) are pinned host memory,
#: which is still host memory.
_DLPACK_HOST = {1, 3, 11}

_DLPACK_NAMES = {2: "CUDA", 4: "OpenCL", 7: "Vulkan", 8: "Metal", 10: "ROCm",
                 13: "CUDA managed", 14: "one-API"}


def _from_any(a):
    """Accept any array that speaks DLPack, not just numpy's.

    DLPack is the cross-library standard for handing over a buffer -- numpy 2,
    torch, cupy and jax all implement ``__dlpack__`` -- so keying off it means
    this works with arrays from libraries matchedfilter has never heard of and
    does not depend on.  Anything older falls through to numpy's own coercion,
    which covers the buffer protocol and ``__array__``.

    Data that already lives on an accelerator is REFUSED rather than copied.
    A silent device-to-host transfer here would be invisible in the API and
    would dominate the runtime of the very kernel the caller came for; a GPU
    tensor reaching the CPU backend is a mistake worth reporting, not
    absorbing.
    """
    if hasattr(a, "__dlpack_device__"):
        try:
            kind = int(a.__dlpack_device__()[0])
        except Exception:
            kind = 1                      # unreadable: let numpy try
        if kind not in _DLPACK_HOST:
            raise TypeError(
                "array is on a %s device; matchedfilter will not copy it to "
                "the host implicitly -- move it yourself (e.g. .cpu()) or "
                "build the filter with the matching device="
                % _DLPACK_NAMES.get(kind, "non-host"))
        try:
            return np.from_dlpack(a)
        except Exception:
            pass                          # e.g. read-only producer; coerce below
    return a


def devices():
    """Every device this build can dispatch to.  See :mod:`matchedfilter.device`."""
    from .device import devices as _devices
    return _devices()


def _as_c64(a, n, what):
    a = np.ascontiguousarray(_from_any(a), dtype=np.complex64)
    if a.ndim != 1 or a.size != n:
        raise ValueError(f"{what} must be a 1-D complex array of {n} samples, got shape {a.shape}")
    return a


from ._errors import UnsupportedSize      # noqa: E402


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

    #: Class-level so subclasses with their own __init__ -- HierarchicalFilter
    #: -- inherit the CPU default instead of raising on first use.
    _gpu = None

    def __init__(self, n, ndata=1, ntemplates=1, device=None):
        from .device import parse as _parse_device
        self.device = _parse_device(device)
        self.n = int(n)
        self.ndata = int(ndata)
        self.ntemplates = int(ntemplates)
        self._buf = None
        self._sbuf = None
        #: Has any spectrum reached the plan? The hierarchical refine path
        #: dereferences the stored pointer, so run() with no set_data() was a
        #: SEGFAULT -- and only once a pair actually fired, which made it look
        #: intermittent rather than like a missing call.
        self._dataset = False
        # Arrays the plan holds pointers into. The C side keeps the caller's
        # spectrum rather than copying it, so the wrapper must keep it alive.
        self._held = {}
        self._gpu = None
        self._gpairs = 0
        self._gtrig = 0
        self._ddirty = True
        self._tdirty = True
        if self.device.kind == "gpu":
            self._start_gpu()
            return
        self._mf = _core.MF(self.n, self.ndata, self.ntemplates)

    # ---- GPU -----------------------------------------------------------
    #
    # The GPU holds the spectra itself rather than handing them to the C
    # plan, so the two paths diverge at ingest and meet again at run().
    # Everything user-visible -- shapes, dtype, bin layout, the index -1
    # convention -- is identical, which is what lets one test body assert
    # against both.
    def _start_gpu(self):
        # One flat-filter contract, two backends behind it. Both expose
        # peaks() with the same signature and the same conventions, so
        # nothing above this line knows which it got.
        #
        # Only the Context differs. Everything after it is shared, and it is
        # written once for that reason: when this was a branch per backend
        # with its own copy of the tail, the hierarchical version's early
        # return skipped the _gcal it was supposed to set, and every Metal
        # call died in _gpu_calibration on a missing attribute.
        if self.n not in _GPU_SIZES:
            raise ValueError(
                "device='gpu' supports n in %s; got %d. Larger transforms need "
                "more than 1024 threads and are not implemented yet, so they "
                "would have to be split across dispatches."
                % (sorted(_GPU_SIZES), self.n))
        self._gpu = self._backend().Context(self.device.index)
        self._gdata = np.zeros((self.ndata, self.n), dtype=np.complex64)
        self._gtmpl = np.zeros((self.ntemplates, self.n), dtype=np.complex64)

    def _backend(self):
        """The compute module for this device: Metal on Apple, else Vulkan."""
        if getattr(self.device, "backend", None) == "metal":
            from . import _mtlcompute
            return _mtlcompute
        from . import _vkcompute
        return _vkcompute

    # ---- ingest -------------------------------------------------------------
    def _ensure(self):
        """The live plan. Always built here; HierarchicalFilter defers."""
        return self._mf

    def _gpu_set(self, store, spectra, index, what):
        if what == "data":
            self._ddirty = True
        else:
            self._tdirty = True
        if index is None:
            a = np.ascontiguousarray(_from_any(spectra), dtype=np.complex64)
            if a.shape != store.shape:
                raise ValueError("expected shape %s, got %s"
                                 % (store.shape, a.shape))
            store[:] = a
        else:
            store[int(index)] = _as_c64(spectra, self.n, "spectrum")

    def set_data(self, spectra, index=None):
        """Set one data spectrum (with ``index``) or all from a (ndata, n) array.

        Inputs are frequency domain - the unnormalised forward transform of the
        segment, natural order.
        """
        if self._gpu is not None:
            self._dataset = True
            return self._gpu_set(self._gdata, spectra, index, "data")
        if index is not None:
            a = _as_c64(spectra, self.n, "spectrum")
            # The plan keeps this pointer -- the coarse band is read straight
            # out of it during run(), and the full spectrum is ingested lazily
            # only if a pair fires. A caller passing a temporary would have it
            # freed before either happens, which is a use-after-free that only
            # shows when the refine path runs. Hold a reference.
            self._held[int(index)] = a
            self._ensure().set_data(int(index), a)
            self._dataset = True
            return
        a = np.ascontiguousarray(spectra, dtype=np.complex64)
        if a.ndim != 2 or a.shape != (self.ndata, self.n):
            raise ValueError(f"expected shape ({self.ndata}, {self.n}), got {a.shape}")
        self._held[-1] = a                      # see the note above
        for i in range(self.ndata):
            self._ensure().set_data(i, a[i])
        self._dataset = True

    def set_templates(self, spectra, index=None):
        """Set one template spectrum (with ``index``) or all from a (ntemplates, n) array.

        Conjugation happens here, once, rather than in the pair loop.
        """
        if self._gpu is not None:
            return self._gpu_set(self._gtmpl, spectra, index, "template")
        if index is not None:
            self._ensure().set_template(int(index), _as_c64(spectra, self.n, "spectrum"))
            return
        a = np.ascontiguousarray(spectra, dtype=np.complex64)
        if a.ndim != 2 or a.shape != (self.ntemplates, self.n):
            raise ValueError(f"expected shape ({self.ntemplates}, {self.n}), got {a.shape}")
        for i in range(self.ntemplates):
            self._ensure().set_template(i, a[i])


    def _gpu_hier(self, D, H, binsize, threshold, start, end):
        """Coarse pass and refinement, in one command buffer on the device.

        Shared by run() and run_series() so the two cannot drift.

        Nothing is read back between the passes. The refining kernel
        evaluates the coarse gate itself, so a dismissed pair's workgroup
        exits immediately and no survivor list ever has to reach the host.
        Doing that on the host cost more than the filtering did: 0.26 ms of
        kernel work inside a 5.0 ms call.
        """
        band, f, thr = self._gpu_calibration(threshold)
        # The coarse templates are a function of the templates and the band,
        # so they are rebuilt only when the templates change.
        #
        # Keyed on WHERE the templates are, not on the identity of the view
        # object. H is a fresh slice of self._gtmpl on every call, so id(H)
        # was a new number every time and this cache never hit once -- it
        # rebuilt nt x band complex twice per run, which at 65536 pairs was
        # 3.9 ms of numpy against 2.1 ms of GPU.
        #
        # id() was also unsound. CPython reuses the address of a freed
        # object, so the next call's view can land on the previous one's id
        # and hit the cache for a DIFFERENT template sub-range of the same
        # shape. The data pointer cannot collide that way: it is the address
        # of the templates themselves, so a different t0 is a different key.
        ck = (band, f, H.ctypes.data, H.shape)
        if getattr(self, "_ckey", None) != ck or self._tdirty:
            sc = 1.0 / np.sqrt(f) if f > 0 else 0.0
            ct0 = (H[:, :band] * sc).astype(np.complex64)
            ramp = np.exp(1j * np.pi * np.arange(band) / band).astype(np.complex64)
            self._ct = (ct0, (ct0 * ramp).astype(np.complex64))
            self._ckey = ck
        ct0, ct1 = self._ct

        idx, val = self._gpu.hier_peaks(
            self.n, band, D, H, ct0, ct1, thr, thr,
            binsize=binsize, threshold=threshold, window=(start, end),
            upload_data=self._ddirty, upload_tmpl=self._tdirty)
        self._ddirty = self._tdirty = False

        # Refine-rate bookkeeping, in one reduction rather than three.
        #
        # This is a diagnostic -- refine_rate and stats read it -- and it
        # used to cost three passes over the output on the hot path: a bool
        # array, then mean(), then sum(). mean IS sum/size, so two of the
        # three were free to remove. At 65536 pairs the block was about
        # 0.1 ms against 0.31 ms of GPU, which is a lot to spend on a
        # number nobody asked for.
        self._gpairs += idx.shape[0] * idx.shape[1]
        fired = (idx >= 0).any(axis=2)
        k = int(fired.sum())
        self._last_refine = (k / fired.size) if fired.size else 0.0
        self._gtrig += k
        return idx, val

    def _run_gpu(self, binsize, threshold, start, end, data, templates,
                 counts, raw):
        """The GPU half of run(), returning exactly what the CPU half does.

        Sub-ranges are taken by slicing the stored spectra rather than by
        telling the kernel about them: the kernel dispatches one workgroup
        per pair, so a sub-range is just a smaller dispatch, and keeping that
        out of the kernel keeps its index arithmetic in one place.
        """
        d0, nd = (0, self.ndata) if data is None else (int(data[0]), int(data[1]))
        t0, nt = (0, self.ntemplates) if templates is None else (int(templates[0]), int(templates[1]))
        if nd < 1 or nt < 1 or d0 < 0 or t0 < 0 \
           or d0 + nd > self.ndata or t0 + nt > self.ntemplates:
            raise ValueError("data/templates sub-range out of bounds")

        if not self._dataset:
            raise ValueError(
                "no data: call set_data() before run(). The plan stores the "
                "caller's spectrum pointer and the hierarchical refine path "
                "is the first thing to dereference it, so this used to be a "
                "segfault, and only once a pair fired.")
        idx, val = self._gpu.peaks(
            self.n, self._gdata[d0:d0 + nd], self._gtmpl[t0:t0 + nt],
            binsize=binsize, threshold=threshold, window=(start, end),
            upload_data=self._ddirty, upload_tmpl=self._tdirty)
        self._ddirty = self._tdirty = False
        if raw:
            r = (idx, val)
            return (r, (idx >= 0).sum(axis=2).astype(np.int32)) if counts else r
        peaks = np.empty(idx.shape, dtype=PEAK_DTYPE)
        peaks["index"] = idx
        peaks["value"] = val
        if counts:
            return peaks, (idx >= 0).sum(axis=2).astype(np.int32)
        return peaks

    # ---- run ----------------------------------------------------------------
    def nbins(self, binsize, window=None):
        start, end = self._window(window)
        if self._gpu is not None:
            return 0 if start >= end else -(-(end - start) // int(binsize))
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
        fields ``index`` (lag, int64) and ``value`` (complex64).  A bin whose
        maximum does not exceed ``threshold`` comes back with ``index == -1``
        and ``value == 0``, so bin j always sits at slot j and the result can
        be indexed by frequency without searching.

        For the magnitude, take ``np.abs(peaks["value"])``.  It was a third
        field once; it equalled that expression exactly, so it only cost a
        copy.

        ``data`` and ``templates`` restrict the run to a sub-range, given as
        ``(start, count)``; the answer is identical to the matching slice of a
        full run.  ``window=(start, end)`` restricts the lags searched.

        With ``counts=True`` returns ``(peaks, counts)``, where counts has shape
        ``(ndata, ntemplates)`` and holds how many bins crossed the threshold.

        ``raw=True`` returns ``(index, value)`` as two plain arrays
        of shape ``(ndata, ntemplates, nbins)`` instead of assembling a
        structured array.  A caller driving small batches in a tight loop pays
        for that assembly on every call -- a field copy here and a
        structured-array slice at the other end -- which can exceed the filter
        work itself.

        THE RESULT IS A REUSED BUFFER, on both paths.  The next ``run`` on this
        filter overwrites it in place; ``.copy()`` anything that must outlive
        that call.  Six allocations are nothing beside a 2^20 transform, but a
        caller driving small batches pays them every time -- at 37 templates
        they were 15 of the 21 us a call took -- so the buffer is kept.  The
        trap is real enough that it caught the first draft of the worked
        example in ``matchedfilter.tutorial``, which compared a full run
        against a windowed one and printed the windowed answer twice.
        """
        n = self.n
        binsize = n if binsize is None else int(binsize)
        start, end = self._window(window)
        if self._gpu is not None:
            return self._run_gpu(binsize, threshold, start, end, data,
                                 templates, counts, raw)
        d0, nd = (0, self.ndata) if data is None else (int(data[0]), int(data[1]))
        t0, nt = (0, self.ntemplates) if templates is None else (int(templates[0]), int(templates[1]))
        if nd < 1 or nt < 1 or d0 < 0 or t0 < 0 \
           or d0 + nd > self.ndata or t0 + nt > self.ntemplates:
            raise ValueError("data/templates sub-range out of bounds")
        nb = self._ensure().nbins(binsize, start, end)
        if not self._dataset:
            raise ValueError(
                "no data: call set_data() before run(). The plan stores the "
                "caller's spectrum pointer and the hierarchical refine path "
                "is the first thing to dereference it, so this used to be a "
                "segfault, and only once a pair fired.")
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
            r = (idx.reshape(nd, nt, nb), val.reshape(nd, nt, nb))
            return (r, cnt.reshape(nd, nt)) if counts else r
        peaks["index"] = idx.reshape(nd, nt, nb)
        peaks["value"] = val.reshape(nd, nt, nb)
        return (peaks, cnt.reshape(nd, nt)) if counts else peaks



    def run_series(self, series, starts, win_start, win_end,
                   binsize=None, threshold=0.0, templates=None, raw=False):
        """Filter a time series over a caller-supplied block layout.

        The caller keeps the overlap-save arithmetic -- where each block starts
        and which span of its output is valid.  matchedfilter only executes
        that plan, which removes the per-block round trip: no separately
        planned forward FFT, no spectrum passed back and forth, and one call
        per segment rather than one per block.

        Windows are per block, so the ragged ones at a segment's edges need no
        grouping.  Returns a structured array of shape
        ``(nblocks, ntemplates, nbins)``, or with ``raw=True`` the two plain
        arrays ``(index, value)`` of that shape.

        Blocks sharing a window are filtered together, up to this filter's own
        ``ndata``.  That is the grouping knob and there is no other: ndata is
        already how many segments the plan can hold, and a second control
        would only let the two disagree.  A filter built with ``ndata=1``
        still gives the same answers, one block at a time.

        THE RETURNED ARRAYS ARE REUSED BUFFERS, as with ``run``.  The next call
        overwrites them; copy anything that has to outlive it.
        """
        ser = np.ascontiguousarray(series, dtype=np.complex64)
        st = np.ascontiguousarray(starts, dtype=np.uintp)
        ws = np.ascontiguousarray(win_start, dtype=np.uintp)
        we = np.ascontiguousarray(win_end, dtype=np.uintp)
        if not (st.size == ws.size == we.size):
            raise ValueError("starts, win_start and win_end must be the same length")
        if st.size < 1:
            raise ValueError("run_series needs at least one block")
        nblk = st.size
        self._dataset = True   # run_series supplies its own blocks
        # Every window must give the same bin count: the result has ONE
        # nbins in its shape and the C addresses peaks at a single stride, so
        # a shorter window at a segment's edge writes into the next block's
        # row and past the end of the buffer. That is reachable from ordinary
        # overlap-save input, and it corrupted the heap rather than failing.
        nbset = {self.nbins(binsize if binsize is not None else self.n,
                            (int(a), int(b))) for a, b in zip(ws, we)}
        if len(nbset) > 1:
            raise ValueError(
                "every block's window must give the same bin count; these "
                "give %s. Use a binsize that divides each window equally, or "
                "call run_series once per distinct window."
                % sorted(nbset))
        if self._gpu is not None:
            return self._run_series_gpu(ser, st, ws, we, binsize, threshold,
                                        templates, raw)
        t0, nt = (0, self.ntemplates) if templates is None else (
            int(templates[0]), int(templates[1]))
        if nt < 1 or t0 < 0 or t0 + nt > self.ntemplates:
            raise ValueError("templates sub-range out of bounds")
        binsize = self.n if binsize is None else int(binsize)
        nb = self._ensure().nbins(binsize, int(ws[0]), int(we[0]))
        need = nblk * nt * nb
        sb = self._sbuf
        if sb is None or sb[0] != (nblk, nt, nb):
            sb = self._sbuf = ((nblk, nt, nb),
                               np.empty(need, dtype=np.int64),
                               np.empty(need, dtype=np.complex64),
                               np.empty(need, dtype=np.float32),
                               np.empty(nblk * nt, dtype=np.int32))
        _, idx, val, mag, cnt = sb
        self._ensure().run_series(ser, st, ws, we, t0, nt, binsize,
                                  float(threshold), idx, val, mag, cnt)
        if raw:
            return idx.reshape(nblk, nt, nb), val.reshape(nblk, nt, nb)
        peaks = np.empty((nblk, nt, nb), dtype=PEAK_DTYPE)
        peaks["index"] = idx.reshape(nblk, nt, nb)
        peaks["value"] = val.reshape(nblk, nt, nb)
        return peaks

    def _series_window(self, spec, H, binsize, threshold, w0, w1, first):
        """One dispatch for the blocks sharing a window. Returns (index, value).

        The only thing the two filters do differently in run_series, which is
        why everything around it is shared.
        """
        gi, gv = self._gpu.peaks(
            self.n, spec, H, binsize=binsize, threshold=threshold,
            window=(w0, w1), upload_data=True,
            upload_tmpl=first or self._tdirty)
        self._tdirty = False
        return gi, gv

    def _run_series_gpu(self, ser, st, ws, we, binsize, threshold,
                        templates, raw):
        """run_series on a GPU plan, flat or hierarchical.

        The C does the per-block forward transform inside the plan; here it is
        done on the host, which is the same arithmetic and keeps the device
        code to the one kernel that already exists.

        Blocks are grouped by window, because a window is a dispatch parameter
        rather than per-pair data: blocks sharing one can go in a single call,
        and only the ragged ones at a segment's edges are left on their own.

        This was written twice, once per filter class, differing in one call.
        The copies then drifted: the hierarchical one lost the 1/n and handed
        its coarse gate spectra n times too large, which is the whole of
        round 0 in docs/iteration-plan.md. Two implementations of one
        algorithm is how that happens, so there is one.
        """
        n = self.n
        nblk = st.size
        t0, nt = (0, self.ntemplates) if templates is None else (
            int(templates[0]), int(templates[1]))
        if nt < 1 or t0 < 0 or t0 + nt > self.ntemplates:
            raise ValueError("templates sub-range out of bounds")
        binsize = n if binsize is None else int(binsize)
        H = self._gtmpl[t0:t0 + nt]

        # One strided gather and one batched transform, rather than a Python
        # loop calling np.fft.fft per block. Blocks may run off the end of the
        # series; the missing tail is zero, as the C's padding makes it.
        #
        # The 1/n is the caller's convention and the C applies it on the way
        # in. Omitting it handed the coarse gate spectra n times too large --
        # _gpu_hier saw |D|max 304.633 against run()'s 0.0743734 at n=4096,
        # exactly 4096 -- so every pair cleared a threshold calibrated for
        # the real scale.
        if nblk:
            grid = (st[:, None].astype(np.int64)
                    + np.arange(n, dtype=np.int64)[None, :])
            inside = grid < ser.size
            # np.minimum keeps the gather in bounds; `inside` zeroes the tail.
            blocks = np.where(inside, ser[np.minimum(grid, max(ser.size - 1, 0))],
                              np.complex64(0))
            spec = (np.fft.fft(blocks, axis=1) / n).astype(np.complex64)
        else:
            spec = np.zeros((0, n), dtype=np.complex64)

        nb = self.nbins(binsize, (int(ws[0]), int(we[0])))
        idx = np.full((nblk, nt, nb), -1, dtype=np.int64)
        val = np.zeros((nblk, nt, nb), dtype=np.complex64)
        first = True
        for w in {(int(a), int(b)) for a, b in zip(ws, we)}:
            rows = np.flatnonzero((ws == w[0]) & (we == w[1]))
            gi, gv = self._series_window(
                np.ascontiguousarray(spec[rows]), H, binsize, threshold,
                w[0], w[1], first)
            first = False
            if gi.shape[2] != nb:
                raise ValueError(
                    "blocks in one call must produce the same bin count; "
                    "window %s gives %d against %d" % (w, gi.shape[2], nb))
            idx[rows] = gi
            val[rows] = gv
        if raw:
            return idx, val
        peaks = np.empty(idx.shape, dtype=PEAK_DTYPE)
        peaks["index"] = idx
        peaks["value"] = val
        return peaks



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


def _uncovered_reference(power, n, t):
    """True when no candidate band has a localised peak to work with.

    A reference whose in-band power sits in a bin or two gives a
    correlation of nearly constant magnitude -- there is no peak to find
    coarsely and refine, so the method does not apply. See `_BEFF_MIN`.
    """
    bands = {cb for (cn, cb, _U, _K, _s, _m) in t["cost"] if cn == n and cb < n}
    if not bands:
        return False
    return all(_band_features(power, b)[1] < _BEFF_MIN for b in bands)


def _uncovered_message(n, snr, fd):
    """Why autotuning refused, and what to do about it.

    Only the DISCRETE choices are limited by these tables. The coarse
    threshold itself is interpolated in (f_eff, snr) by src/hmf_table.h over
    snr 4.5 to 8.0 and clamps conservatively outside, so the threshold adapts
    to any request; what is missing here is measured evidence for which band,
    oversampling, taps and margin to pair it with.
    """
    t = _load_tuning()
    ns = sorted(set(t.get("acc2_snrs", {})) | {r[0] for r in t["fdr"]})
    snrs = t.get("acc2_snrs", {}).get(n) or _complete_snrs(t, n)
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
            "Either pass band/taps explicitly, or generate "
            "coverage with tools/hmf_tune.py and point MF_ACCURACY and "
            "MF_COST at it. See docs/hierarchical.md."
            % (n, snr, fd, where, ns, snrs or "none at this n"))


#: Where the parsed tables are cached. Beside the package if that is
#: writable, otherwise the user cache directory; if neither is, the cache is
#: skipped and the text is parsed as before.
def _cache_path(paths):
    import hashlib
    key = hashlib.sha1("|".join(
        "%s:%d" % (q, int(os.path.getmtime(q))) for q in paths
        if os.path.exists(q)).encode()).hexdigest()[:16]
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.path.join(
            os.environ.get("XDG_CACHE_HOME",
                           os.path.expanduser("~/.cache")), "matchedfilter")):
        try:
            os.makedirs(base, exist_ok=True)
            if os.access(base, os.W_OK):
                return os.path.join(base, "tuning-%s.pkl" % key)
        except Exception:
            continue
    return None


def _cached_tuning(paths):
    """Load the parsed tables from a cache keyed on the text files' mtimes.

    Parsing the shipped tables is 54 ms of pure Python -- 30000 lines, nine
    float() calls each -- and it lands wherever the caller first builds a
    plan. In pycbc_inspiral_fir that is inside the timed kernel, where it made
    the first segment 50 ms against a steady-state 8 ms and read as a 28%
    regression.
    
    Two attempts to parse faster were both SLOWER than the loop (np.array on
    split rows 74 ms, np.fromstring 64 ms) because the cost is building 11264
    tuples and 2048 dict entries, not converting the floats. So the parse is
    skipped instead: a pickle of the result loads in 6.6 ms, 8x faster.

    The text files stay the source of truth. The cache key is their paths and
    modification times, so editing one or pointing MF_COST somewhere else
    misses the cache and reparses rather than serving something stale.
    """
    if not paths:
        return None
    cp = _cache_path(paths)
    if cp is None or not os.path.exists(cp):
        return None
    try:
        import pickle
        with open(cp, "rb") as fh:
            t = pickle.load(fh)
        t["paths"] = list(paths)
        return t
    except Exception:
        return None          # a corrupt or stale-format cache is not fatal


def _store_tuning(t, paths):
    cp = _cache_path(paths)
    if cp is None:
        return
    try:
        import pickle
        tmp = cp + ".%d" % os.getpid()
        with open(tmp, "wb") as fh:
            pickle.dump({k: v for k, v in t.items() if k != "paths"}, fh,
                        protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, cp)          # atomic, so a concurrent reader is safe
    except Exception:
        pass



def cost_table_for(device):
    """Path to the cost table that best describes `device`, and its key.

    Cost is a property of the machine. The accuracy rows describe the
    ALGORITHM and travel unchanged; the cost rows do not, and selecting with
    another machine's is how a configuration that is cheapest somewhere else
    gets chosen here.

    Tables are tried most specific first -- exact architecture, then family,
    then vendor -- and the shipped generic table, measured on a CPU, is the
    last resort. Returns ``(path, key)`` where key is None for the generic
    one, so a caller can say which was used rather than leaving it implied.
    """
    here = os.path.dirname(__file__)
    if os.environ.get("MF_COST"):
        return os.environ["MF_COST"], "MF_COST"
    for key in getattr(device, "arch", ()) or ():
        candidate = os.path.join(here, "cost-%s.txt" % key)
        if os.path.exists(candidate):
            return candidate, key
    return os.path.join(here, "cost.txt"), None


def accuracy_table_for(device):
    """Path to the accuracy table describing the algorithm `device` runs.

    Accuracy rows say how often a configuration DISMISSES a signal it should
    have kept, so they describe the algorithm, not the machine. There used
    to be a separate GPU table because the two did not run the same
    algorithm: the CPU interpolated the coarse peak where the GPU escalated
    the whole window. The CPU no longer interpolates -- it cost more in taps
    than the correlations it saved -- so both now run the same three steps:
    coarse pass, one threshold, refine.

    Measured after that convergence, same reference and band with only the
    device changing, the GPU still dismisses slightly LESS: 0.96, 0.86 and
    0.90 of the CPU's rate at band 512 over margins 1.10 to 1.22, on 114 to
    1156 events a cell. Small, systematic, and in the safe direction -- so
    the CPU's rate is an upper bound on the GPU's and one table serves both.

    The per-backend lookup stays even though nothing uses it now, because
    the day they diverge the other way there has to be somewhere to put the
    answer, and discovering that on a wrong result is expensive.

    Resolved rather than assumed, so the day the two diverge the other way
    there is somewhere to put the answer. Most specific first: the backend,
    then any GPU, then the shipped default. Both GPU backends run the same
    Slang kernels, so "gpu" is the level that usually matters.

    Returns ``(path, key)`` with key None for the default, so a caller can
    say which was used rather than leaving it implied.
    """
    here = os.path.dirname(__file__)
    if os.environ.get("MF_ACCURACY"):
        return os.environ["MF_ACCURACY"], "MF_ACCURACY"
    keys = []
    backend = getattr(device, "backend", None)
    if getattr(device, "kind", None) == "gpu":
        if backend:
            keys.append(backend)
        keys.append("gpu")
    for key in keys:
        candidate = os.path.join(here, "accuracy-%s.txt" % key)
        if os.path.exists(candidate):
            return candidate, key
    return os.path.join(here, "accuracy.txt"), None


def _load_tuning_for(device):
    """Tuning for one device: accuracy for its algorithm, cost for its machine."""
    cost, _ck = cost_table_for(device)
    acc, _ak = accuracy_table_for(device)
    # cache=False: this must NOT become the process-wide table. It did, and
    # then every later caller -- including CPU plans -- got the GPU's cost
    # rows, which cover fewer transform lengths, so a CPU plan at a length
    # the GPU table does not carry failed with "no measured tuning".
    return _load_tuning_paths([acc, cost], cache=False)


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
             os.environ.get("MF_COST") or os.path.join(here, "cost.txt"),
             # The measured coarse thresholds. Separate file because it is a
             # different KIND of row -- a threshold rather than a rate or a
             # cost -- and because it is the one that replaces a model.
             os.environ.get("MF_THRESHOLD")
             or os.path.join(here, "threshold.txt")]
    if path is not None:
        paths = [path]
    return _load_tuning_paths(paths, cache=path is None)


def _load_tuning_paths(paths, cache=True):
    global _TUNING
    # The cache is keyed on these paths, so it can only be consulted AFTER
    # they are known. Looking it up first -- which an earlier version did --
    # meant every fresh process missed, reparsed, and then rewrote the cache
    # it had just failed to read: 59 ms instead of 50, worse than no cache.
    cached = _cached_tuning(tuple(paths))
    if cached is not None:
        if cache:
            _TUNING = cached
        return cached
    fdr, cost, acc2, acc2r, thr, meta = [], {}, {}, {}, {}, {}
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
            elif f[0] == "ACC2":
                # ACC2 n K snr f beff margin dismissal
                #
                # Band is NOT in this key, and that is the point. Measured
                # at n=8192, f=0.99, B_eff=16, dismissal across bands 256,
                # 512, 1024 and 2048 is 1.64, 1.88, 1.77 and 1.75e-2 -- a
                # 1.14x spread inside the error bars, over band/B_eff from
                # 16 to 128. A candidate band enters only through the
                # (f, B_eff) its own edge produces, which selection computes
                # from the reference anyway.
                #
                # B_eff is sampled ABSOLUTELY here. The old grid sampled it
                # as a fraction of the band, which tied it to the variable
                # that does not matter and never reached the small values
                # real references have -- the FIR-search reference sits at
                # B_eff 1.1 at every band.
                acc2.setdefault((int(f[1]), int(f[2]), round(float(f[3]), 2),
                                 round(float(f[6]), 3)), []).append(
                                     (float(f[4]), float(f[5]), float(f[7])))
            elif f[0] == "THR":
                # THR n snr f ratio fd threshold
                #
                # The measured coarse threshold. Not a margin on a model --
                # the number itself, bisected against measured dismissal
                # until it meets fd. Keyed on (f, ratio) because those are
                # what the statistic depends on, both dimensionless.
                thr.setdefault((int(f[1]), round(float(f[2]), 2),
                                float(f[5])), []).append(
                                    (float(f[3]), float(f[4]), float(f[6])))
            elif f[0] == "ACC2R":
                # ACC2R n K snr f ratio margin dismissal
                #
                # The successor key. ACC2 sampled B_eff absolutely, 2 to 128,
                # and measured every cell at band 1024 -- so a real reference,
                # whose B_eff is 154 to 384, was extrapolated on every lookup.
                # Worse, what scalloping depends on is neither band nor B_eff
                # but their RATIO:
                #
                #   peak width in lag ~ n/B_eff, lag step = n/band
                #   samples across the peak = band/B_eff, with no n in it
                #
                # ACC2 covered ratio 8 to 512. The reference this library
                # exists for sits at 1.66 (band 256), 2.83 (512), 5.33 (1024).
                # The oversample doubled that and hid it; without the
                # oversample, 1.66 samples across a peak is critically
                # undersampled and dismissal goes 12x. Measured at the ratio,
                # keyed on the ratio.
                acc2r.setdefault((int(f[1]), int(f[2]), round(float(f[3]), 2),
                                  round(float(f[6]), 3)), []).append(
                                      (float(f[4]), float(f[5]), float(f[7])))
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
    acc2_snrs = {}
    for (an, aK, asnr, amg) in acc2:
        acc2_snrs.setdefault(an, set()).add(asnr)
    acc2r_snrs = {}
    for (an, aK, asnr, amg) in acc2r:
        acc2r_snrs.setdefault(an, set()).add(asnr)
    t = {"fdr": fdr, "cost": cost, "meta": meta, "paths": paths,
         "acc2": acc2,
         "acc2_snrs": {k: sorted(v) for k, v in acc2_snrs.items()},
         "acc2r": acc2r,
         "thr": thr,
         "acc2r_snrs": {k: sorted(v) for k, v in acc2r_snrs.items()},
         "by_ns": by_ns, "snrs_at": snrs_at,
         "cost_cfg": {k: sorted(v) for k, v in cost_cfg.items()}}
    _store_tuning(t, tuple(paths))
    if cache or _TUNING is None:
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


#: Cost differences inside this fraction are treated as a tie.
#:
#: This was added believing the limit was RESOLUTION -- the rows are
#: pivot-relative ratios with a few percent of spread. Regenerating the table
#: with eight noise realisations a cell, which takes the ratio CV to under 1%
#: at n=4096, showed otherwise: the better-sampled table scored WORSE (91%
#: against 100% at n=4096 snr 6.0), because the ordering was already wrong and
#: sampling converged onto the wrong value more precisely.
#:
#: The error is BIAS, in the harness. tools/hmf_tune.py builds its cost plans
#: with ntemplates=1 and divides by nt as though it had batched -- it measures
#: the unbatched regime. Real use runs a bank, where the coarse pass amortises
#: across templates and the tap count scales differently, which is exactly the
#: axis it gets wrong: it puts 512/2/8 ahead of 512/2/4 where measurement has
#: the latter 10.6% faster.
#:
#: So this is a patch over a systematic error. Fix the harness workload, then
#: delete it -- do not tune it.
_COST_TIE = 0.05


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


#: Below this effective bandwidth the reference has no localised
#: correlation peak and the method has nothing to exploit.
#:
#: B_eff is the participation ratio of the in-band power, so B_eff = 1 means
#: one frequency bin, whose inverse transform has CONSTANT magnitude across
#: every lag. There is no peak to find coarsely and refine. What the coarse
#: pass loses there is not scalloping at all: it is that the full search
#: takes its maximum over more samples of the same flat field, measured at
#: 0.879 against a predicted sqrt(ln band / ln n) = 0.866 -- a 12% systematic
#: under-read that the recovery factors do not model, because they model
#: peak shape.
#:
#: Every real reference measured sits at B_eff 130-225; the degenerate ones
#: at 1-2. So the cut is loose on purpose and anything in 4 to 32 gives the
#: same answer for every reference seen. It is a statement about when the
#: algorithm applies, not a tuned threshold.
_BEFF_MIN = 8.0

#: Divisor on the budget before the margin is placed. The lookup is an
#: ESTIMATE -- an interpolation between measured cells -- and a budget
#: wants a bound, so this is what stands between the two.
#:
#: Measured by tools/score_fdr.py, which requests a budget, takes whatever
#: selection returns, and measures what that configuration really
#: dismisses. Over 48 cases spanning three reference families, four
#: lengths and two thresholds, realised/requested runs 0.43x at the
#: median, 2.11x at p90 and 4.21x at worst.
#:
#: Left at 1.0 and overridable, because the right value is a policy rather
#: than a measurement: half the cases are already twice as safe as asked,
#: so a factor large enough to cover the tail makes the median far safer
#: than requested and pays escalation for it.
_FDR_SAFETY = float(os.environ.get("MF_FDR_SAFETY", "1.0"))


def _spread(v):
    """Scale for one feature axis: its standard deviation, never zero."""
    if len(v) < 2:
        return 1.0
    m = sum(v) / len(v)
    sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5
    return sd if sd > 1e-9 else 1.0


def _idw(rows, f, be, k=4, power=2.0, log=False, floor=1e-12):
    """Inverse-distance interpolation of `rows` = (f, B_eff, value).

    A convex combination of measured cells, so it can never return a value
    outside them. That is why it is inverse distance and not a fitted
    surface: a least-squares plane over the same scattered rows extrapolates
    past the edge of the data, and when it was scored it picked band 256 at
    n=8192 and n=16384 where the measured best is 4096 and 2048 -- 41-50% of
    the available speedup, against 98.3% for this.

    Distances are in units of each feature's spread across the rows, so
    neither axis dominates through its units: f runs 0 to 1 and B_eff runs
    to hundreds of bins.

    `log=True` interpolates the logarithm, which is what dismissal needs --
    it moves by orders of magnitude across the grid while the features move
    by factors.
    """
    if not rows:
        return None
    sf, sb = _spread([r[0] for r in rows]), _spread([r[1] for r in rows])
    d2 = sorted((((tf - f) / sf) ** 2 + ((tb - be) / sb) ** 2, v)
                for (tf, tb, v) in rows)
    near = d2[:max(k, 1)]
    if near[0][0] < 1e-18:
        return near[0][1]
    if log:
        ws = [(d ** (-0.5 * power), math.log10(max(v, floor))) for d, v in near]
        return 10.0 ** (sum(w * v for w, v in ws) / sum(w for w, _ in ws))
    ws = [(d ** (-0.5 * power), v) for d, v in near]
    return sum(w * v for w, v in ws) / sum(w for w, _ in ws)


def choose_threshold(power, n, snr, fd, band, tuning=None):
    """The measured coarse threshold for this reference at this band.

    Interpolates the THR table at the reference's own (f, ratio). No model,
    no margin: the table stores the threshold that met `fd` when it was
    measured, so selection reads it rather than deriving one and correcting
    it. Returns None where nothing was measured, which makes the caller
    refuse rather than guess.
    """
    t = _load_tuning() if tuning is None else tuning
    rows_by_fd = t.get("thr", {})
    if not rows_by_fd:
        return None
    f, be = _band_features(power, band)
    if be <= 0:
        return None
    ratio = band / be
    # Ask for a tighter budget than requested, by the same safety factor the
    # margin path used. The table's rows are measurements with their own
    # Poisson error, and interpolating between them in (f, ratio) adds more,
    # so spending the budget exactly leaves nothing for either. A tighter
    # budget gives a LOWER threshold, so this errs toward escalating.
    want = fd / _FDR_SAFETY
    cands = sorted({k[2] for k in rows_by_fd if k[0] == n})
    if not cands:
        return None
    use_fd = max([c for c in cands if c <= want * 1.001] or [min(cands)])
    snrs = sorted({k[1] for k in rows_by_fd if k[0] == n and k[2] == use_fd})
    if not snrs:
        return None
    lo = max([x for x in snrs if x <= snr] or [snrs[0]])
    rows = rows_by_fd.get((n, lo, use_fd)) or []
    if not rows:
        return None
    # Inverse-distance in log(f), log(ratio) -- the two axes the threshold
    # varies along, both dimensionless.
    #
    # This was briefly a conservative bound instead: the largest row measured
    # at f' <= f and ratio' <= ratio, on the reasoning that a guarantee wants
    # a bound rather than an estimate. It was introduced to fix a budget test
    # failing at 4 omissions in 120 -- and that failure does not move when
    # the threshold does, 4/120 at both 4.76 interpolated and 4.00 bounded,
    # so it is not the coarse gate at all. The bound fixed nothing and cost
    # throughput, so it is gone.
    num = den = 0.0
    for rf, rr, rt in rows:
        d = (np.log(max(rf, 1e-9) / max(f, 1e-9)) ** 2
             + np.log(max(rr, 1e-9) / max(ratio, 1e-9)) ** 2)
        if d < 1e-12:
            return float(rt)
        w = 1.0 / d
        num += w * rt
        den += w
    return float(num / den) if den else None


def _choose_v2(power, n, snr, fd, t):
    """Cheapest configuration whose ESTIMATED dismissal meets the budget.

    One rule, applied the same way to both tables: interpolate at the
    reference's own (f, B_eff), place the margin to hit the budget, price
    the result, take the cheapest. No covering sets, no bracketing, no
    special cases -- those all existed to make a lookup behave like a bound,
    and a bound is not what this needs. What it needs is an estimate plus a
    measured safety factor.
    """
    snrs = t.get("acc2r_snrs", {}).get(n) or t["acc2_snrs"].get(n)
    if not snrs:
        return None
    use, _why = _snr_rows_for(snr, snrs)
    if use is None:
        return None
    floor = _dismissal_floor(t)

    bands, kus = set(), set()
    for (cn, cb, cU, cK, _cs, _cm) in t["cost"]:
        if cn == n and cb < n:
            bands.add(cb)
            kus.add((cU, cK))

    best, bcost, bcfg = None, float("inf"), None
    for band in sorted(bands):
        f, be = _band_features(power, band)
        if be < _BEFF_MIN:
            continue                       # no peak to localise; see _BEFF_MIN
        # Samples across the correlation peak: peak width in lag is ~n/B_eff
        # and the coarse lag step is n/band, so this is the dimensionless
        # quantity scalloping depends on -- no n in it. ACC2R is keyed on it.
        ratio = (band / be) if be > 0 else float("inf")
        use_r = bool(t.get("acc2r_snrs", {}).get(n))
        for (U, K) in sorted(kus):
            src = t["acc2r"] if use_r else t["acc2"]
            margins = sorted({m for (an, aK, asnr, m) in src
                              if an == n and aK == K and asnr in use})
            curve = []
            for mg in margins:
                # worst over the SNR rows that speak for this threshold
                est = [x for x in
                       (_idw(src.get((n, K, s_, mg)) or [], f,
                             ratio if use_r else be,
                             log=True, floor=floor) for s_ in use)
                       if x is not None]
                if est:
                    curve.append((mg, max(est)))
            if not curve:
                continue
            mg = _margin_at_budget(curve, fd / _FDR_SAFETY, floor)
            if mg is None:
                continue
            crows = []
            for cs in _cost_snrs(t, n, band, U, K, mg, use):
                crows += t["cost"].get((n, band, U, K, round(cs, 2), mg)) or []
            if not crows:
                # the cost grid is coarser in margin than the accuracy grid;
                # price at the nearest measured margin rather than skipping
                have = t["cost_cfg"].get((n, band, U, K)) or []
                near = min((abs(m2 - mg), m2) for m2 in
                           {m3 for (c1, c2, c3, c4, _s, m3) in t["cost"]
                            if (c1, c2, c3, c4) == (n, band, U, K)} or {1.0})[1]
                for cs in _cost_snrs(t, n, band, U, K, near, use):
                    crows += t["cost"].get((n, band, U, K, round(cs, 2), near)) or []
            if not crows:
                continue
            c = _idw(crows, f, be)
            if c is not None and c < bcost:
                # U is gone from the interface. The shipped cost rows still
                # carry the column because every one of them was measured at
                # U=2; it is a lookup detail here and disappears when the
                # tables are regenerated without it.
                best, bcost, bcfg = (band, K), c, (band, K, round(mg, 4))
    return bcfg


def choose_config(power, n, snr, fd, tuning=None):
    """Cheapest (band, taps) whose measured dismissal meets `fd`.

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
    if t.get("acc2r_snrs", {}).get(n) or t.get("acc2_snrs", {}).get(n):
        return _choose_v2(power, n, snr, fd, t)
    # --- everything below is the OLD key, kept only for lengths the
    # re-keyed table does not cover yet. Delete it once ACC2 covers every
    # supported length; nothing here is worth preserving on its merits.
    #
    # Only thresholds whose band coverage matches the fullest available at
    # this length. A partially measured threshold is worse than an absent one:
    # it looks like an exact hit, so the bracketing rule never fires, and
    # selection is silently restricted to whichever bands happen to have rows.
    # Adding snr 5.75 for newly measured bands alone did exactly that -- at
    # n=2048 it forced band 1024 where 5.5 and 6.0 both choose 512, and the
    # speedup fell from 3.60x to 2.07x.
    tsnrs = t["snrs_at"].get(n)
    if not tsnrs:
        return None
    use, why = _snr_rows_for(snr, tsnrs)
    if use is None:
        return None

    # Resolve the threshold PER CONFIGURATION, not once for the whole table.
    #
    # Coverage is ragged: at n=4096 snr 6.5 was measured for bands 256, 512
    # and 1024 but not 2048. Discarding the whole threshold for that -- which
    # an earlier "complete coverage only" guard did -- fell back to the snr
    # 6.0 rows, a strictly harder problem, and handed every band a margin near
    # 0.907 when 0.976 was admissible. It cost the n=4096 snr 6.5 point 9.01x
    # against 5.66x.
    #
    # So each configuration uses its own rows at the requested threshold when
    # it has them, and only falls back to the conservative bracketing rule
    # where it does not. A band measured at 6.5 is judged at 6.5; one that is
    # not is judged at 6.0 and priced accordingly.
    feats, byconf = {}, {}
    exact = [s_ for s_ in tsnrs if abs(s_ - snr) <= 1e-6]
    at_snr = {}
    for s_ in tsnrs:
        for r in t["by_ns"].get((n, s_), ()):
            at_snr.setdefault((r[1], r[2], r[3], r[7]), set()).add(s_)
    rows = []
    for cfg, have in at_snr.items():
        pick = exact if (exact and exact[0] in have) else [u for u in use if u in have]
        if not pick:
            pick = sorted(have)
        rows += [r for s_ in pick for r in t["by_ns"].get((n, s_), ())
                 if (r[1], r[2], r[3], r[7]) == cfg]
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
        # Near-ties go to the higher margin, which is the more robust choice.
        #
        # The cost rows are ratios with a residual spread of 2-3%, so a gap
        # that small is not a ranking -- it is noise, and following it is a
        # coin flip. Measured at n=4096 snr 6.0: the table separates
        # 512/2/8 m0.907 (0.716) from 512/2/4 m1.000 (0.741) by 3.5% and puts
        # them the wrong way round; the real gap is 10.6% the other way.
        #
        # A higher margin means a higher coarse threshold, so fewer pairs
        # escalate. That is worth having for its own sake when the price is
        # inside the measurement error: escalation is the part of the cost
        # that depends on the caller's data rather than on the machine, so the
        # higher-margin configuration is the one whose measured cost will
        # still hold on data that is not the design case.
        if c < bcost * (1.0 - _COST_TIE) or (
                best is not None and c < bcost * (1.0 + _COST_TIE)
                and margin > bmargin + 1e-9):
            best, bcost, bmargin = (band, U, K), min(c, bcost), margin
        elif best is None:
            best, bcost, bmargin = (band, U, K), c, margin
    if best is None:
        return None
    # (band, taps, margin). The oversample used to sit between band and
    # taps; it is gone, and this path is the only one that still had it,
    # because the lengths it serves are the ones ACC2 never covered.
    return (best[0], best[2], round(bmargin, 4))


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
    margin against your data - and can be pinned with ``band`` /
    ``taps`` for testing.  How the work is *arranged*, on the other hand, is
    chosen here and not by the caller: see :meth:`run_series`.
    """

    def __init__(self, n, ndata=1, ntemplates=1, snr=5.5, fd=1e-2,
                 band=None, taps=None, device=None):
        from .device import parse as _parse_device
        self.device = _parse_device(device)
        self.n = int(n)
        self.ndata = int(ndata)
        self.ntemplates = int(ntemplates)
        self.snr = float(snr)
        self.fd = float(fd)
        self._buf = None
        self._sbuf = None
        #: Has any spectrum reached the plan? The hierarchical refine path
        #: dereferences the stored pointer, so run() with no set_data() was a
        #: SEGFAULT -- and only once a pair actually fired, which made it look
        #: intermittent rather than like a missing call.
        self._dataset = False
        self._held = {}
        self._pending_ref = None
        self._cal_thr = None
        self._thr_applied = False
        self._pinned = None
        self._fs_snr = None
        self._last_refine = 0.0
        self._gpu = None
        self._gpairs = 0
        self._gtrig = 0
        self._ddirty = True
        self._tdirty = True
        if self.device.kind == "gpu":
            # HierarchicalFilter overrides __init__, so it does NOT inherit
            # MatchedFilter's call to _start_gpu. Omitting this left device=
            # accepted, self.device reporting "gpu:0", and every run quietly
            # going to the CPU -- which looked like a working port.
            #
            # The pinned configuration is recorded BEFORE returning. Returning
            # first skipped the band handling below, so a caller who pinned a
            # configuration got the table's choice instead and config()
            # reported the substitute rather than what was asked for.
            if band is not None:
                self._pinned = (int(band), int(taps or 8))
            self._start_gpu()
            self._defer = True
            self._mf = None
            return
        if band is None:
            # Defer: the band should be chosen from the reference, and the
            # reference arrives after construction in every caller we have.
            # Building the plan on first use instead of here means the choice
            # can see it, with no rebuild and no re-ingest of templates.
            self._mf = None
            self._defer = True
        else:
            self._defer = False
            self._pinned = (int(band), int(taps or 8))
            self._mf = _core.HMF(self.n, self.ndata, self.ntemplates, self.snr,
                                 self.fd, self._pinned[0], 1, self._pinned[1])
            if self._cal_thr is not None:
                self._mf.set_threshold(self._cal_thr)

    def _ensure(self):
        """Build the plan, choosing its configuration if that was deferred.

        The band should be chosen from the reference, and every caller sets
        the reference after construction -- so the plan is built on first use
        instead of in __init__.  That lets the choice see the reference with
        no rebuild and no re-ingest of templates.
        """
        if self._mf is not None:
            # A plan pinned in __init__ was built BEFORE set_reference, so
            # its threshold could not be looked up then -- the table is
            # keyed on the reference's own (f, ratio). Do it on first use,
            # once, now that the reference is here.
            #
            # Without this a pinned plan ran with a threshold derived from
            # an empty reference, which is 0: the coarse gate disabled and
            # every pair escalated. It dismissed nothing, so every budget
            # assertion on a pinned plan passed by doing no gating at all.
            if (not self._thr_applied and self._cal_thr is None
                    and self._pending_ref is not None):
                self._thr_applied = True
                try:
                    tv = choose_threshold(self._pending_ref, self.n, self.snr,
                                          self.fd, int(self.config[0]))
                except Exception:
                    tv = None
                if tv is not None:
                    self._mf.set_threshold(float(tv))
            return self._mf
        cfg = None
        if self._pinned is not None:
            # A pinned configuration is an instruction, not a hint.
            #
            # On the CPU path __init__ builds the plan immediately and this
            # returns above. On the GPU path it records the pin and leaves
            # _mf None -- so without this, the first _ensure() threw the pin
            # away and asked the table, and then REFUSED for any reference
            # the table does not cover, even though the caller had already
            # said what to run. Pinning exists precisely to run something
            # the tables do not describe, which is what the tuner does on
            # every cell.
            cfg = self._pinned + (1.0,)
        elif self._pending_ref is not None:
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
            if self._pending_ref is not None:
                try:
                    bad_ref = _uncovered_reference(self._pending_ref, self.n,
                                                   _load_tuning())
                except Exception:
                    bad_ref = False
                if bad_ref:
                    raise ValueError(
                        "the reference has no localised correlation peak at "
                        "n=%d: every candidate band has an effective "
                        "bandwidth below %.0f bins, which means its in-band "
                        "power sits in a bin or two and the correlation "
                        "magnitude is nearly constant across every lag. "
                        "There is nothing for a coarse pass to localise, so "
                        "the hierarchical mode does not apply -- use "
                        "MatchedFilter. A reference that looks like this is "
                        "usually |h|^2 without the 1/S(f), or a spectrum "
                        "with no low-frequency cutoff."
                        % (self.n, _BEFF_MIN))
            raise ValueError(_uncovered_message(self.n, self.snr, self.fd))
        b, k, margin = cfg
        self._mf = _core.HMF(self.n, self.ndata, self.ntemplates,
                             self.snr, self.fd, int(b), 1, int(k))
        # The MEASURED threshold for this reference at this band, if the
        # table covers it. It replaces the modelled one outright -- no
        # margin, no recovery factor, no Rice model -- so the number the
        # coarse pass is compared against is the number that was measured
        # to meet the budget.
        if self._cal_thr is None and self._pending_ref is not None:
            try:
                tv = choose_threshold(self._pending_ref, self.n, self.snr,
                                      self.fd, int(b))
            except Exception:
                tv = None
            if tv is not None:
                self._mf.set_threshold(float(tv))
                # The margin no longer means anything -- it scaled a modelled
                # threshold and there is no model now -- but it is still
                # recorded and formatted downstream, so leave it at 1.0
                # rather than None. set_threshold overrides it regardless.
                margin = 1.0
        if self._cal_thr is not None:
            # A caller-supplied threshold overrides whatever the table chose.
            self._mf.set_threshold(self._cal_thr)
        if self._pending_ref is not None:
            self._mf.set_reference(self._pending_ref)
        return self._mf

    # ---- GPU -----------------------------------------------------------
    #
    # The port is tractable because of one fact src/hmf.c states outright:
    # the coarse pass IS a matched filter on an m-point plan. It is not a
    # bespoke decimation -- it is the ordinary flat filter at length `band`,
    # on templates truncated to that band and scaled by 1/sqrt(f). So the
    # coarse pass needs no kernel of its own; it is the kernel that already
    # ships, at a shorter length.
    #
    # The second fact that makes it simple: with a reference set, the three
    # coarse thresholds are SCALARS, not per-template. fpow and the recovery
    # factors then come from the reference rather than from each template, so
    # every template gets the same numbers -- verified across 32 templates
    # with deliberately different power-law slopes.
    def _start_gpu(self):
        # Same one-contract-two-backends shape as the flat filter, plus the
        # calibration cache. Written as one path for the reason given there.
        if self.n not in _GPU_SIZES:
            raise ValueError(
                "device='gpu' supports n in %s; got %d"
                % (sorted(_GPU_SIZES), self.n))
        self._gpu = self._backend().Context(self.device.index)
        self._gdata = np.zeros((self.ndata, self.n), dtype=np.complex64)
        self._gtmpl = np.zeros((self.ntemplates, self.n), dtype=np.complex64)
        self._gcal = None

    def _gpu_calibration(self, threshold):
        """(band, f, threshold) for this reference.

        The GPU runs the CPU's algorithm now -- coarse pass, one threshold,
        refine -- so it reads the same measured threshold from the same
        table. It used to build a 1x1 CPU plan purely to read three numbers
        out of it, because the threshold was a Rice model plus measured
        recovery factors and a second implementation of those would have
        been a second thing to keep in step. There is no model left to keep
        in step: choose_threshold IS the implementation.

        The CPU plan is still built when the table cannot bound this
        reference, because that is the path that still derives a threshold.
        Three slots are returned where one number goes, so every caller and
        both backends keep their shape.
        """
        key = (threshold, self.snr, self.fd, self._fs_snr, self._pinned)
        if self._gcal is not None and self._gcal[0] == key:
            return self._gcal[1]
        # An explicitly pinned configuration must be honoured. Building the
        # calibration plan without it silently substituted the table's own
        # choice, so HierarchicalFilter(..., band=256, device="gpu") ran at
        # band 512 and reported 512 -- a caller asking for a configuration
        # got a different one.
        pin = {}
        if self._pinned is not None:
            pin = dict(band=self._pinned[0], taps=self._pinned[1])
        else:
            # Choose the configuration with THIS DEVICE's cost rows. Letting
            # the calibration plan choose for itself used the shipped table,
            # which is a CPU's -- so the GPU picked whichever band is
            # cheapest on an AVX-512 core.
            path, self._cost_key = cost_table_for(self.device)
            try:
                cfg = choose_config(self._pending_ref, self.n, self.snr,
                                    self.fd, tuning=_load_tuning_for(self.device))
            except Exception:
                cfg = None
            if cfg is not None:
                pin = dict(band=cfg[0], taps=cfg[1])
        # The measured threshold, read directly. No CPU plan, no model.
        if pin.get("band") and self._pending_ref is not None:
            tv = None
            try:
                tv = choose_threshold(self._pending_ref, self.n, self.snr,
                                      self.fd, int(pin["band"]))
            except Exception:
                tv = None
            if tv is not None:
                band = int(pin["band"])
                ref = np.asarray(self._pending_ref, dtype=np.float64)
                f = float(ref[:band].sum() / ref.sum()) if ref.sum() > 0 else 0.0
                self._gcfg = (band, int(pin.get("taps") or 8))
                out = (band, f, float(tv))
                self._gcal = (key, out)
                return out

        cal = HierarchicalFilter(self.n, 1, 1, snr=self.snr, fd=self.fd, **pin)
        # Order matters: set_first_stage builds the plan, and building it
        # before the reference arrives means the band is chosen with nothing
        # to choose from, which fails with "no measured tuning" on a
        # configuration the tables cover perfectly well.
        cal.set_reference(self._pending_ref)
        cal.set_templates(self._gtmpl[0][None, :])
        if self._fs_snr is not None:
            cal.set_first_stage(self._fs_snr)
        plan = cal._ensure()
        band = cal.config[0]
        thr = plan.coarse_threshold(float(threshold))
        ref = np.asarray(self._pending_ref, dtype=np.float64)
        f = float(ref[:band].sum() / ref.sum()) if ref.sum() > 0 else 0.0
        self._gcfg = cal.config          # the real (band, taps)
        out = (band, f, thr)
        self._gcal = (key, out)
        return out

    def _run_gpu(self, binsize, threshold, start, end, data, templates,
                 counts, raw_out):
        """Coarse pass, then the flat filter on what survives.

        Two dispatches for the coarse halves and one per data segment for the
        refinement. That is more round trips than the fused kernel wants --
        the survivor list goes to the host and back -- and it is the first
        thing to remove once this is correct. Correctness first: a fused
        kernel that is wrong is harder to diagnose than a slow one.
        """
        d0, nd = (0, self.ndata) if data is None else (int(data[0]), int(data[1]))
        t0, nt = (0, self.ntemplates) if templates is None else (int(templates[0]), int(templates[1]))
        if nd < 1 or nt < 1 or d0 < 0 or t0 < 0 \
           or d0 + nd > self.ndata or t0 + nt > self.ntemplates:
            raise ValueError("data/templates sub-range out of bounds")
        if self._pending_ref is None:
            raise ValueError("set_reference is required before running on a GPU")
        if not self._dataset:
            raise ValueError(
                "no data: call set_data() before run(). The plan stores the "
                "caller's spectrum pointer and the hierarchical refine path "
                "is the first thing to dereference it, so this used to be a "
                "segfault, and only once a pair fired.")


        D = self._gdata[d0:d0 + nd]
        H = self._gtmpl[t0:t0 + nt]

        idx, val = self._gpu_hier(D, H, binsize, threshold, start, end)
        peaks = np.empty(idx.shape, dtype=PEAK_DTYPE)
        peaks["index"] = idx
        peaks["value"] = val
        if raw_out:
            r = (peaks["index"], peaks["value"])
            return (r, (peaks["index"] >= 0).sum(axis=2).astype(np.int32)) if counts else r
        if counts:
            return peaks, (peaks["index"] >= 0).sum(axis=2).astype(np.int32)
        return peaks

    def set_coarse_threshold(self, value):
        """Set the coarse threshold directly, bypassing the design tables.

        The coarse pass reports one number per pair -- the maximum of the
        band-limited correlation -- and this is what it is compared against.
        Above it the pair gets the full filter; below it the pair is
        dismissed. That is the whole decision.

        Autotuning exists to choose this number for a false-dismissal budget,
        and needs measured tables to do it. A caller who knows what threshold
        they want does not: set it here and no table is consulted, no
        reference is required for the threshold (one is still needed for the
        coarse band itself), and nothing is modelled. The guarantee becomes
        whatever the caller's own threshold implies, which is the honest
        trade for not asking the library to promise a budget.

        Pass None to go back to the table.
        """
        if value is None:
            self._cal_thr = None
            if self._mf is not None:
                self._mf.set_threshold(-1.0)
            return
        self._cal_thr = float(value)
        if self._mf is not None:
            self._mf.set_threshold(float(value))

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
        better should say so here.  Band and taps are fixed when
        the plan is built and are not affected.

        The design table's SNR grid starts at 4.5, and the level is
        interpolated on it, so anything lower **clamps to 4.5** rather than
        going further.  The call succeeds either way; if you need the first
        stage looser than that, widen the band instead.

        Pass ``None`` or a non-positive value to go back to deriving it.
        """
        self._fs_snr = None if snr is None else float(snr)
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


    def _series_window(self, spec, H, binsize, threshold, w0, w1, first):
        """The hierarchical dispatch: coarse gate, then refine what survives.

        Everything else in run_series is the base class's.
        """
        return self._gpu_hier(spec, H, binsize, threshold, w0, w1)

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
        ``(nblocks, ntemplates, nbins)``, or with ``raw=True`` the two plain
        arrays ``(index, value)`` of that shape -- which skips
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
        self._dataset = True   # run_series supplies its own blocks
        # Every window must give the same bin count: the result has ONE
        # nbins in its shape and the C addresses peaks at a single stride, so
        # a shorter window at a segment's edge writes into the next block's
        # row and past the end of the buffer. That is reachable from ordinary
        # overlap-save input, and it corrupted the heap rather than failing.
        nbset = {self.nbins(binsize if binsize is not None else self.n,
                            (int(a), int(b))) for a, b in zip(ws, we)}
        if len(nbset) > 1:
            raise ValueError(
                "every block's window must give the same bin count; these "
                "give %s. Use a binsize that divides each window equally, or "
                "call run_series once per distinct window."
                % sorted(nbset))
        if self._gpu is not None:
            return self._run_series_gpu(ser, st, ws, we, binsize, threshold,
                                        templates, raw)
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
            # Two, as every other entry point returns -- including this
            # method's own GPU branch, which is what made CPU and GPU
            # disagree on one call and stopped hierarchical-on-GPU running
            # end to end. A peak is where and what, nothing else; magnitude
            # is np.abs(value) exactly, so returning it only copied.
            return idx.reshape(nblk, nt, nb), val.reshape(nblk, nt, nb)
        peaks = np.empty((nblk, nt, nb), dtype=PEAK_DTYPE)
        peaks["index"] = idx.reshape(nblk, nt, nb)
        peaks["value"] = val.reshape(nblk, nt, nb)
        return peaks

    @property
    def config(self):
        """``(band, taps)`` the design table selected."""
        if self._gpu is not None:
            self._gpu_calibration(self.snr)
            return self._gcfg
        band, _u, k = self._ensure().config()
        return band, k

    @property
    def cost_table(self):
        """Which cost table selection used, or None for the generic one.

        Worth being able to ask: a device with no measurements of its own
        falls back to a CPU's, which is a real difference in what was
        chosen, and it should not be something a user has to infer.
        """
        if self._gpu is None:
            return None
        self._gpu_calibration(self.snr)
        return getattr(self, "_cost_key", None)

    @property
    def stats(self):
        """``(pairs, triggers)`` accumulated since construction."""
        if self._gpu is not None:
            return (self._gpairs, self._gtrig)
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
        if self._gpu is not None:
            # No C plan to accumulate counters, so this is the LAST run's
            # rate rather than a lifetime one. Stated because the CPU's is
            # a lifetime figure and comparing them silently would mislead.
            return self._last_refine
        pairs, trig = self._ensure().stats()
        return trig / pairs if pairs else 0.0


# Read and index the tuning tables at IMPORT, not at the first plan build.
#
# Doing it lazily meant the cost landed wherever a caller first constructed a
# HierarchicalFilter, and callers construct those inside their hot loop:
# pycbc_inspiral_fir builds its plan inside the timed kernel, so a 10 ms load
# showed up as 10 ms of filtering on the first segment and nothing thereafter.
# Import is the one place that is unambiguously not in anyone's measurement,
# and it already costs ~70 ms for numpy and the extension, so this is ~14% of
# something already paid.
#
# Guarded, because a missing or unreadable table must not break `import
# matchedfilter` -- only the hierarchical mode needs it, and _ensure()
# diagnoses its absence properly with a message about coverage.
try:
    _load_tuning()
except Exception:
    pass


def __getattr__(name):
    """Expose ``Device`` without enumerating hardware at import time.

    Listing devices creates a Vulkan instance, which is far too much work to
    do on ``import matchedfilter`` for the majority of callers who will only
    ever use the CPU.
    """
    if name == "Device":
        from .device import Device
        return Device
    raise AttributeError(name)
