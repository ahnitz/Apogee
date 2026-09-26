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

CPU lengths are powers of two from 64 to 1048576. GPU lengths are powers
of two from 64 to 65536, subject to device limits. Hierarchical calibration
coverage is separate from transform support.
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
#: transform and n = threads * points-per-thread, so the 1024-thread cap puts
#: the ceiling at 16384 while a thread holds 16 points, at 32768 while it
#: holds 32, and at 65536 while it holds 64. Above that the transform state
#: no longer fits the register file and the four-step has to be split across
#: dispatches -- a different kernel, so 65536 is where this one ends.
#:
#: Keep in step with tools/build_spirv.py TIER_B, which is what emits them.
#: The short lengths were built as coarse bands before they were offered as
#: transform lengths -- the kernel generalises down without change, so they
#: cost nothing to expose and close the bottom of the CPU's range.
_GPU_SIZES = frozenset((64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384,
                        32768, 65536))

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
    if isinstance(a, np.ndarray):
        return a
    if hasattr(a, "__dlpack_device__"):
        try:
            kind = int(a.__dlpack_device__()[0])
        except Exception:
            kind = 1                      # unreadable: let numpy try
        if kind not in _DLPACK_HOST:
            raise TypeError(
                "array is on a %s device; matchedfilter will not copy it to "
                "the host implicitly. External accelerator allocations cannot be "
                "imported by the Vulkan/Metal backends; use empty_shared() "
                "for host-visible GPU storage, or transfer explicitly"
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


def _format_result(idx, val, *, raw=False, counts=None, out=None, order=None):
    """Assemble the public dtype once, or return separate raw arrays."""
    if counts is True:
        counts = (idx >= 0).sum(axis=2).astype(np.int32)
    if raw:
        if order is None:
            result = (idx.astype(np.int64, copy=False), val)
        else:
            ri = np.empty(idx.shape, np.int64)
            rv = np.empty(val.shape, np.complex64)
            ri[order], rv[order] = idx, val
            result = ri, rv
    else:
        result = np.empty(idx.shape, PEAK_DTYPE) if out is None else out
        if order is None:
            result["index"], result["value"] = idx, val
        else:
            result["index"][order], result["value"][order] = idx, val
    return (result, counts) if counts is not None and counts is not False else result


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
        if self.ndata < 1 or self.ntemplates < 1:
            raise ValueError("ndata and ntemplates must be >= 1")
        self._init_state()
        if self.device.kind == "gpu":
            self._start_gpu()
            return
        self._mf = _core.MF(self.n, self.ndata, self.ntemplates)

    def _init_state(self):
        self._buf = None
        self._sbuf = None
        #: Has any spectrum reached the plan? The hierarchical refine path
        #: dereferences the stored pointer, so run() with no set_data() was a
        #: SEGFAULT -- and only once a pair actually fired, which made it look
        #: intermittent rather than like a missing call.
        self._dataset = False
        self._data_ready = set()
        self._template_ready = set()
        # Arrays the plan holds pointers into. The C side keeps the caller's
        # spectrum rather than copying it, so the wrapper must keep it alive.
        self._held = {}
        self._gpu = None
        self._gpairs = 0
        self._gtrig = 0
        self._ddirty = True
        self._tdirty = True

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
        self._gdata = None  # series execution uses its own workspace
        self._gtmpl = None

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

    def _input_index(self, index, size):
        if index is None:
            return None
        index = int(index)
        if index < 0 or index >= size:
            raise IndexError("index %d out of range" % index)
        return index

    def _mark_ready(self, kind, index):
        attr = "_" + kind + "_ready"
        ready = getattr(self, attr)
        if index is None:
            setattr(self, attr, None)  # complete bank: constant-time hot-path check
        elif ready is not None:
            ready.add(index)
            size = self.ndata if kind == "data" else self.ntemplates
            if len(ready) == size:
                setattr(self, attr, None)

    def _missing(self, kind, start, count):
        ready = getattr(self, "_" + kind + "_ready")
        return ready is not None and any(i not in ready for i in range(start, start + count))

    def _require_templates(self, start, count):
        if self._missing("template", start, count):
            raise ValueError("no templates for requested rows: call set_templates() first")

    def _gpu_set(self, store, spectra, index, what):
        if what == "data":
            self._ddirty = True
        else:
            self._tdirty = True
        if index is None:
            a = np.ascontiguousarray(_from_any(spectra), dtype=np.complex64)
            shape = (self.ndata if what == "data" else self.ntemplates, self.n)
            if a.shape != shape:
                raise ValueError("expected shape %s, got %s" % (shape, a.shape))
            from ._shared import shared_buffer
            attr = "_gdata" if what == "data" else "_gtmpl"
            if shared_buffer(a, self._gpu) is not None:
                setattr(self, attr, a)
            elif store is None or shared_buffer(store, self._gpu) is not None or not store.flags.writeable:
                setattr(self, attr, a.copy())
            else:
                store[:] = a
        else:
            if store is None:
                shape = (self.ndata if what == "data" else self.ntemplates, self.n)
                store = np.zeros(shape, dtype=np.complex64)
                setattr(self, "_gdata" if what == "data" else "_gtmpl", store)
            if not store.flags.writeable:
                store = store.copy()
                setattr(self, "_gdata" if what == "data" else "_gtmpl", store)
            store[int(index)] = _as_c64(spectra, self.n, "spectrum")

    def set_data(self, spectra, index=None):
        """Set one data spectrum (with ``index``) or all from a (ndata, n) array.

        Inputs are frequency domain - the unnormalised forward transform of the
        segment, natural order.
        """
        index = self._input_index(index, self.ndata)
        if self._gpu is not None:
            self._gpu_set(self._gdata, spectra, index, "data")
            self._dataset = True
            self._mark_ready("data", index)
            return
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
            self._mark_ready("data", index)
            return
        a = np.ascontiguousarray(_from_any(spectra), dtype=np.complex64)
        if a.ndim != 2 or a.shape != (self.ndata, self.n):
            raise ValueError(f"expected shape ({self.ndata}, {self.n}), got {a.shape}")
        self._held[-1] = a                      # see the note above
        for i in range(self.ndata):
            self._ensure().set_data(i, a[i])
        self._held = {-1: a}
        self._dataset = True
        self._mark_ready("data", None)

    def set_templates(self, spectra, index=None):
        """Set one template spectrum (with ``index``) or all from a (ntemplates, n) array.

        Conjugation happens here, once, rather than in the pair loop.
        """
        index = self._input_index(index, self.ntemplates)
        if self._gpu is not None:
            self._gpu_set(self._gtmpl, spectra, index, "template")
            self._mark_ready("template", index)
            return
        if index is not None:
            self._ensure().set_template(int(index), _as_c64(spectra, self.n, "spectrum"))
            self._mark_ready("template", index)
            return
        a = np.ascontiguousarray(_from_any(spectra), dtype=np.complex64)
        if a.ndim != 2 or a.shape != (self.ntemplates, self.n):
            raise ValueError(f"expected shape ({self.ntemplates}, {self.n}), got {a.shape}")
        for i in range(self.ntemplates):
            self._ensure().set_template(i, a[i])
        self._mark_ready("template", None)


    def _gpu_pair_limit(self):
        limit = getattr(self._gpu, 'max_dispatch_x', 2**32 - 1)
        # Large transforms can exceed a driver's submission timeout when a
        # whole bank runs at once. Bound worst-case work, including a fully
        # admitted hierarchical batch, independently of storage capacity.
        if self.n >= 32768:
            limit = min(limit, (1 << 29) // self.n)
        return limit

    def _gpu_window(self, D, H, binsize, threshold, start, end):
        nd, nt = D.shape[0], H.shape[0]
        limit = self._gpu_pair_limit()
        if nd * nt <= limit:
            return self._gpu_dispatch(D, H, binsize, threshold, start, end)
        nb = 1 + (end - start - 1) // binsize
        idx = np.empty((nd, nt, nb), np.int32)
        val = np.empty((nd, nt, nb), np.complex64)
        for t0 in range(0, nt, limit):
            t1 = min(t0 + limit, nt)
            rows = max(1, limit // (t1 - t0))
            for d0 in range(0, nd, rows):
                d1 = min(d0 + rows, nd)
                gi, gv = self._gpu_dispatch(D[d0:d1], H[t0:t1], binsize,
                                           threshold, start, end)
                idx[d0:d1, t0:t1], val[d0:d1, t0:t1] = gi, gv
        return idx, val

    def _gpu_dispatch(self, D, H, binsize, threshold, start, end):
        idx, val = self._gpu.peaks(
            self.n, D, H, binsize=binsize, threshold=threshold,
            window=(start, end), upload_data=self._ddirty,
            upload_tmpl=self._tdirty)
        self._ddirty = self._tdirty = False
        return idx, val

    # ---- run ----------------------------------------------------------------
    def _execution_plan(self):
        return self._ensure()

    def nbins(self, binsize, window=None):
        binsize = int(binsize)
        if binsize < 1:
            raise ValueError("binsize must be >= 1")
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

        Results may reuse buffers; do not rely on retention across calls.  The next ``run`` on this
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
        if binsize < 1:
            raise ValueError("binsize must be >= 1")
        start, end = self._window(window)
        d0, nd = (0, self.ndata) if data is None else (int(data[0]), int(data[1]))
        t0, nt = (0, self.ntemplates) if templates is None else (int(templates[0]), int(templates[1]))
        if nd < 1 or nt < 1 or d0 < 0 or t0 < 0 \
           or d0 + nd > self.ndata or t0 + nt > self.ntemplates:
            raise ValueError("data/templates sub-range out of bounds")
        if not self._dataset or self._missing("data", d0, nd):
            raise ValueError(
                "no data: call set_data() before run(). The plan stores the "
                "caller's spectrum pointer and the hierarchical refine path "
                "is the first thing to dereference it, so this used to be a "
                "segfault, and only once a pair fired.")
        self._require_templates(t0, nt)
        if self._gpu is not None:
            idx, val = self._gpu_window(
                self._gdata[d0:d0 + nd], self._gtmpl[t0:t0 + nt],
                binsize, threshold, start, end)
            return _format_result(idx, val, raw=raw, counts=bool(counts))
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
            mag = np.empty(0, dtype=np.float32)
            cnt = np.empty(rows, dtype=np.int32)
            peaks = np.empty((nd, nt, nb), dtype=PEAK_DTYPE)
            buf = self._buf = ((rows, nb), idx, val, mag, cnt, peaks)
        _, idx, val, mag, cnt, peaks = buf
        peaks = peaks.reshape(nd, nt, nb)
        self._execution_plan().run(d0, nd, t0, nt, binsize, float(threshold), start, end,
                     idx, val, mag, cnt)
        return _format_result(idx.reshape(nd, nt, nb), val.reshape(nd, nt, nb),
                              raw=raw, counts=cnt.reshape(nd, nt) if counts else None,
                              out=peaks)


    def _series_layout(self, series, starts, win_start, win_end, binsize, templates):
        """Validate the shared series contract before either native backend."""
        ser = np.ascontiguousarray(_from_any(series), dtype=np.complex64)
        st = np.ascontiguousarray(_from_any(starts), dtype=np.uintp)
        ws = np.ascontiguousarray(_from_any(win_start), dtype=np.uintp)
        we = np.ascontiguousarray(_from_any(win_end), dtype=np.uintp)
        if any(a.ndim != 1 for a in (ser, st, ws, we)):
            raise ValueError("series, starts, win_start and win_end must be one-dimensional")
        if not (st.size == ws.size == we.size):
            raise ValueError("starts, win_start and win_end must be the same length")
        if st.size < 1:
            raise ValueError("run_series needs at least one block")
        # Negative signed offsets wrap on conversion to uintp. Also reserve
        # room for the block's sample offsets in the GPU's signed gather.
        if np.any(st > np.iinfo(np.intp).max - self.n):
            raise ValueError("starts must be nonnegative and fit in the sample index range")
        binsize = self.n if binsize is None else int(binsize)
        if binsize < 1:
            raise ValueError("binsize must be >= 1")
        t0, nt = (0, self.ntemplates) if templates is None else (
            int(templates[0]), int(templates[1]))
        if nt < 1 or t0 < 0 or t0 + nt > self.ntemplates:
            raise ValueError("templates sub-range out of bounds")
        self._require_templates(t0, nt)
        from ._series import SeriesLayout
        layout = SeriesLayout(self.n, st, ws, we, binsize)
        return ser, layout, binsize, t0, nt

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

        Equal-window blocks are grouped internally; output retains caller order.
        Flat CPU batches use up to ``ndata`` slots. Hierarchical CPU batches
        use a bounded internal group (normally eight). GPU batches follow the
        series memory budget independently of ``ndata``.

        Raw CPU results reuse buffers; copy retained results.
        A later run() requires set_data() again because series execution
        uses the plan's data slots. This rule applies on both devices.
        """
        ser, layout, binsize, t0, nt = self._series_layout(
            series, starts, win_start, win_end, binsize, templates)
        if self._gpu is not None or self.ndata > 1 or isinstance(self, HierarchicalFilter):
            layout.group(materialize=self._gpu is not None)
        st, ws, we = layout.starts, layout.low, layout.high
        nblk = st.size
        # CPU series execution reuses the data slots. Require fresh spectra
        # before a later run(), consistently on both devices.
        self._dataset = False
        self._data_ready = set()
        if self._gpu is not None:
            return self._run_series_gpu(ser, layout, binsize, threshold, t0, nt, raw)
        nb = layout.nbins
        need = nblk * nt * nb
        sb = self._sbuf
        if sb is None or sb[0] != (nblk, nt, nb):
            sb = self._sbuf = ((nblk, nt, nb),
                               np.empty(need, dtype=np.int64),
                               np.empty(need, dtype=np.complex64),
                               np.empty(0, dtype=np.float32),
                               np.empty(nblk * nt, dtype=np.int32))
        _, idx, val, mag, cnt = sb
        self._execution_plan().run_series(ser, st, ws, we, t0, nt, binsize,
                                  float(threshold), idx, val, mag, cnt)
        return _format_result(idx.reshape(nblk, nt, nb), val.reshape(nblk, nt, nb),
                              raw=raw, order=layout.order)

    def _series_window(self, spec, H, binsize, threshold, w0, w1):
        # Each group has fresh spectra, even when it reuses an allocation.
        self._ddirty = True
        return self._gpu_window(spec, H, binsize, threshold, w0, w1)

    def _run_series_gpu(self, ser, layout, binsize, threshold, t0, nt, raw):
        """Execute shared layout groups with bounded FFT/gather storage."""
        n, nb, nblk = self.n, layout.nbins, layout.starts.size
        H = self._gtmpl[t0:t0 + nt]
        from ._shared import shared_buffer
        if ser.size > np.iinfo(np.uint32).max:
            raise ValueError("GPU series exceeds the 32-bit sample address range")
        budget = getattr(self, "_series_batch_bytes", 64 * 1024 * 1024)
        batch = min(nblk, 65535, max(1, self._gpu_pair_limit() // nt),
                    max(1, budget // (8*n + 4 + 12*nt*nb)))
        source_shared = shared_buffer(ser, self._gpu) is not None
        workspace = getattr(self, "_series_workspace", None)
        if workspace is None or workspace[0] != (batch, n):
            workspace = ((batch, n), None, self._gpu.empty_shared((batch, n)),
                         self._gpu.empty_shared(batch, np.uint32))
        _, source, spectra, starts = workspace
        if source_shared:
            source = ser
            self._series_workspace = (workspace[0], None, spectra, starts)
        else:
            if source is None or source.size < ser.size:
                source = self._gpu.empty_shared(ser.shape)
            source[:ser.size] = ser
            self._series_workspace = (workspace[0], source, spectra, starts)
            source = source[:ser.size]
        # A single group needs no aggregate buffers or scatter.
        single = len(layout.groups) == 1 and nblk <= batch
        if not single:
            idx = np.empty((nblk, nt, nb), dtype=np.int64)
            val = np.empty((nblk, nt, nb), dtype=np.complex64)
        for w0, w1, a, b in layout.groups:
            for begin in range(a, b, batch):
                end = min(begin + batch, b)
                count = end - begin
                starts[:count] = np.minimum(layout.starts[begin:end], ser.size)
                spec = spectra[:count]
                self._gpu.forward(n, source, starts[:count], spec, defer=True)
                try:
                    gi, gv = self._series_window(spec, H, binsize, threshold, w0, w1)
                finally:
                    self._gpu.cancel_forward()
                if single:
                    return _format_result(gi, gv, raw=raw)
                idx[begin:end], val[begin:end] = gi, gv
        return _format_result(idx, val, raw=raw, order=layout.order)

    def empty_shared(self, shape, dtype=np.complex64):
        """Allocate a NumPy array backed by this filter's GPU shared memory.

        CPU filters return ordinary NumPy storage. On GPU, contiguous full
        banks passed to the setters bind directly without an input copy.
        Keep mutations outside run/run_series calls; call the setter again
        after editing a bank to invalidate hierarchical coarse caches.
        NumPy views and CPU DLPack consumers retain the allocation's lifetime.
        This does not export a CUDA/ROCm allocation or an asynchronous stream.
        """
        if self._gpu is None:
            return np.empty(shape, dtype=dtype)
        return self._gpu.empty_shared(shape, dtype)

    def set_memory_limits(self, *, cache_bytes=None, series_bytes=None):
        """Set GPU dispatch-cache and series-temporary budgets in bytes.

        Defaults: 512 MiB of dispatch buffers, 32 storage shapes (and up to
        256 Vulkan command recordings), and 64 MiB of series working storage. A single dispatch/block can exceed a
        budget. The source-series upload (unless already shared) and final
        returned output are not included in the batch working budget.
        Changing the cache budget releases existing dispatch buffers.
        """
        if self._gpu is None:
            raise ValueError("memory budgets apply to GPU filters")
        for value in (cache_bytes, series_bytes):
            if value is not None and int(value) < 1:
                raise ValueError("memory budgets must be positive")
        if cache_bytes is not None:
            self.clear_cache()
            self._gpu.cache_limit_bytes = int(cache_bytes)
        if series_bytes is not None:
            self._series_batch_bytes = int(series_bytes)

    def clear_cache(self):
        """Release GPU dispatch buffers, keeping spectra and compiled pipelines."""
        if self._gpu is not None:
            self._gpu.clear_cache()
            self._series_workspace = None
            self._ddirty = self._tdirty = True




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
    bands = {cb for (cn, cb, _U, _K, _s) in t["cost"] if cn == n and cb < n}
    if not bands:
        return False
    return all(_band_features(power, b)[1] < _BEFF_MIN for b in bands)


def _uncovered_message(n, snr, fd):
    t = _load_tuning()
    ns = sorted({k[0] for k in t["cost"]})
    return ("no measured tuning for n=%d snr=%.2f fd=%.0e: cost coverage "
            "is n=%s, and the gate model must resolve the requested budget. "
            "Provide a reference and measured costs (tools/hmf_tune.py, "
            "MF_COST), or set both band and coarse threshold explicitly."
            % (n, snr, fd, ns))


#: Where the parsed tables are cached. Beside the package if that is
#: writable, otherwise the user cache directory; if neither is, the cache is
#: skipped and the text is parsed as before.
def _cache_path(paths):
    import hashlib
    key = hashlib.sha1(("cost-v2|" + "|".join(
        "%s:%d:%d" % (q, os.stat(q).st_mtime_ns, os.path.getsize(q)) for q in paths
        if os.path.exists(q))).encode()).hexdigest()[:16]
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

    Cost is a property of the machine. The gate model describes the
    algorithm; selecting costs with
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


def _load_tuning_for(device):
    """Device-specific measured costs; every device uses the same gate model."""
    cost, _ = cost_table_for(device)
    return _load_tuning_paths([cost], cache=False)


def _load_tuning(path=None):
    """Read measured runtime costs. Accuracy is computed from the profile."""
    cache = path is None
    path = path or os.environ.get("MF_COST") or os.path.join(
        os.path.dirname(__file__), "cost.txt")
    if cache and _TUNING is not None and _TUNING["paths"] == [path]:
        return _TUNING
    return _load_tuning_paths([path], cache=cache)


def _load_tuning_paths(paths, cache=True):
    global _TUNING
    cached = _cached_tuning(tuple(paths))
    if cached is not None:
        if cache:
            _TUNING = cached
        return cached
    cost, meta = {}, {}
    for one in paths:
        with open(one) as fh:
            for number, line in enumerate(fh, 1):
                f = line.split()
                if not f:
                    continue
                if f[0] == "#":
                    if len(f) > 2 and f[1] in ("cpu", "commit", "trials"):
                        meta[f[1]] = " ".join(f[2:])
                    continue
                if f[0].startswith("#"):
                    continue
                if f[0] != "COST" or len(f) != 9:
                    raise ValueError("%s:%d: expected COST n band U K snr f beff relative_cost; "
                                     "regenerate old tuning files" % (one, number))
                n, band, u, k = map(int, f[1:5])
                snr, fraction, beff, value = map(float, f[5:])
                if (n <= band or band < 64 or band & (band - 1)
                        or not np.isfinite([snr, fraction, beff, value]).all()
                        or snr <= 0 or not 0 < fraction <= 1
                        or beff <= 0 or value <= 0):
                    raise ValueError("%s:%d: invalid cost row" % (one, number))
                cost.setdefault((n, band, u, k, snr), []).append((fraction, beff, value))
    t = {"cost": cost, "meta": meta, "paths": list(paths)}
    _store_tuning(t, tuple(paths))
    if cache:
        _TUNING = t
    return t


def _band_features(power, m):
    """(in-band fraction, effective bandwidth in bins) at band m.

    These are cost-interpolation features, not sufficient statistics for
    accuracy. Gate placement uses the complete reference profile.
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


# References without a localised correlation peak are outside automatic selection.
_BEFF_MIN = 8.0


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
    """Compute the gate from the complete reference profile.

    ``tuning`` remains accepted for source compatibility but cannot affect
    accuracy. Returns None when the sampling budget cannot resolve ``fd``.
    The profile must describe the templates; a heterogeneous bank needs
    separate reference groups or an explicitly validated coarse threshold.
    """
    for obsolete in ("MF_ACCURACY", "MF_THRESHOLD"):
        if os.environ.get(obsolete):
            raise ValueError("%s is retired: use the reference gate model, or set "
                             "an explicit band and coarse threshold" % obsolete)
    from .gatemodel import gate_for
    return gate_for(power, n, band, snr, fd)


def _cost_candidates(power, n, snr, t):
    """Rank configurations using measured costs at the nearest SNR per configuration.

    Costs only rank candidates, never set the gate. Coverage is resolved per
    configuration so a partially measured SNR cannot hide other bands.
    """
    configs = {}
    for cn, band, u, k, s in t["cost"]:
        if cn == n and band < n:
            configs.setdefault((band, u, k), []).append(s)
    candidates = []
    for (band, u, k), snrs in configs.items():
        f, be = _band_features(power, band)
        if be < _BEFF_MIN:
            continue
        use = min(snrs, key=lambda s: (abs(s - snr), s))
        rows = t["cost"][(n, band, u, k, use)]
        value = _idw(rows, f, be)
        if value is not None:
            candidates.append(dict(band=band, U=u, K=k, f=f, beff=be,
                                   crows=rows, cost=value))
    return sorted(candidates, key=lambda c: (c["cost"], c["band"], c["K"]))


def choose_config(power, n, snr, fd, tuning=None):
    """Cheapest measured (band, taps) whose model gate resolves the budget.

    Only costs come from files. The model uses the complete reference at
    the requested SNR and budget, without a tabulated accuracy fallback.
    Cost measurements are approximate rankings, not runtime guarantees.
    """
    t = _load_tuning() if tuning is None else tuning
    for candidate in _cost_candidates(power, n, snr, t):
        band = candidate["band"]
        if choose_threshold(power, n, snr, fd, band) is not None:
            return band, candidate["K"]
    return None


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

    Every reported peak is refined by the full filter. Compare values across
    devices within float32 roundoff, not bitwise. The coarse gate can omit
    peaks; ``fd`` is its modelled false-dismissal target at strength ``snr``,
    not a distribution-independent bound. Use :class:`MatchedFilter` to
    avoid coarse-gate omissions.

    ``snr`` is the |rho| of the weakest signal that must be kept; ``fd`` is the
    tolerated false-dismissal probability for such a signal. Configuration
    comes from measured cost files; the coarse threshold is computed from
    the complete reference profile. Unresolvable budgets raise. Alternatively, explicitly
    set ``band`` and call ``set_coarse_threshold(value)``; this mode needs no
    cost file or reference. ``taps`` remains configuration metadata for
    existing tables; execution uses the raw coarse maximum without interpolation.
    """

    def __init__(self, n, ndata=1, ntemplates=1, snr=5.5, fd=1e-2,
                 band=None, taps=None, device=None):
        from .device import parse as _parse_device
        self.device = _parse_device(device)
        self.n = int(n)
        self.ndata = int(ndata)
        self.ntemplates = int(ntemplates)
        if self.ndata < 1 or self.ntemplates < 1:
            raise ValueError("ndata and ntemplates must be >= 1")
        if band is not None:
            band = int(band)
            if band < 64 or band >= self.n or band & (band - 1):
                raise ValueError("band must be a power of two, >= 64 and < n")
        if taps is not None:
            taps = int(taps)
            if taps < 2 or taps > 64 or taps % 2:
                raise ValueError("taps must be even and between 2 and 64")
        self.snr = float(snr)
        self.fd = float(fd)
        self._init_state()
        self._pending_ref = None
        self._cal_thr = None
        self._thr_applied = False
        self._pinned = None
        self._fs_snr = None
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
            if not self._thr_applied:
                tv = self._coarse_value(self._mf.config()[0], required=False)
                if tv is not None:
                    self._mf.set_threshold(tv)
                    self._thr_applied = True
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
            cfg = self._pinned
        elif self._pending_ref is not None:
            cfg = choose_config(self._pending_ref, self.n, self.snr, self.fd)
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
        b, k = cfg
        self._mf = _core.HMF(self.n, self.ndata, self.ntemplates,
                             self.snr, self.fd, int(b), 1, int(k))
        tv = self._coarse_value(b, required=False)
        if tv is not None:
            self._mf.set_threshold(tv)
            self._thr_applied = True
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
    # A supplied reference gives a common power fraction; pinned plans may
    # instead normalize each coarse template by its own power fraction.
    def _start_gpu(self):
        # Same one-contract-two-backends shape as the flat filter, plus the
        # calibration cache. Written as one path for the reason given there.
        if self.n not in _GPU_SIZES:
            raise ValueError(
                "device='gpu' supports n in %s; got %d"
                % (sorted(_GPU_SIZES), self.n))
        self._gpu = self._backend().Context(self.device.index)
        self._gdata = None  # series execution uses its own workspace
        self._gtmpl = None
        self._gcal = None

    def _coarse_value(self, band, *, required=True):
        """Resolve one gate from an explicit value or the reference model."""
        if self._cal_thr is not None:
            if self._pinned is None:
                raise ValueError("an explicit coarse threshold requires an explicit band")
            return float(self._cal_thr)
        value = None
        if self._pending_ref is not None:
            value = choose_threshold(self._pending_ref, self.n,
                                     self._fs_snr or self.snr, self.fd, int(band))
        if value is None and required:
            raise ValueError(
                "no calibrated coarse threshold for n=%d band=%d: provide a "
                "reference and a resolvable budget, or set both band and coarse threshold"
                % (self.n, band))
        if value is not None and (not np.isfinite(value) or value < 0
                                  or value > float(np.finfo(np.float32).max)):
            raise ValueError("calibrated coarse threshold must be finite, nonnegative float32")
        return None if value is None else float(value)

    def _execution_plan(self):
        plan = self._ensure()
        if not self._thr_applied:
            plan.set_threshold(self._coarse_value(plan.config()[0]))
            self._thr_applied = True
        return plan

    def _gpu_calibration(self, threshold):
        """Use the same profile model or explicit gate as the CPU."""
        key = (self.snr, self.fd, self._fs_snr, self._pinned, self._cal_thr)
        if self._gcal is not None and self._gcal[0] == key:
            return self._gcal[1]
        cfg = self._pinned
        if cfg is None:
            if self._pending_ref is None:
                raise ValueError("set_reference is required for file-based configuration selection")
            _, self._cost_key = cost_table_for(self.device)
            cfg = choose_config(self._pending_ref, self.n, self.snr, self.fd,
                                tuning=_load_tuning_for(self.device))
        if cfg is None:
            raise ValueError(_uncovered_message(self.n, self.snr, self.fd))
        band, taps = cfg
        tv = self._coarse_value(band)
        f = None
        if self._pending_ref is not None:
            ref = np.asarray(self._pending_ref, dtype=np.float64)
            f = float(ref[:band].sum() / ref.sum())
        self._gcfg = (int(band), int(taps))
        out = (int(band), f, tv)
        self._gcal = (key, out)
        return out

    def _gpu_dispatch(self, D, H, binsize, threshold, start, end):
        """Run coarse filtering and refinement without host survivor readback."""
        band, f, thr = self._gpu_calibration(threshold)
        # Fresh views can share an address; view identity is not a cache key.
        # Template/reference changes set _tdirty, even for in-place updates.
        ck = (band, f, H.ctypes.data, H.shape)
        if getattr(self, "_ckey", None) != ck or self._tdirty:
            if f is None:
                power = np.abs(H.astype(np.complex128)) ** 2
                total = power.sum(axis=1)
                fraction = np.divide(power[:, :band].sum(axis=1), total,
                                     out=np.zeros_like(total), where=total > 0)
                sc = np.divide(1.0, np.sqrt(fraction),
                               out=np.zeros_like(fraction), where=fraction > 0)[:, None]
            else:
                sc = 1.0 / np.sqrt(f) if f > 0 else 0.0
            ct0 = (H[:, :band] * sc).astype(np.complex64)
            self._ct = ct0
            self._ckey = ck
        ct0 = self._ct

        idx, val = self._gpu.hier_peaks(
            self.n, band, D, H, ct0, thr,
            binsize=binsize, threshold=threshold, window=(start, end),
            upload_data=self._ddirty, upload_tmpl=self._tdirty)
        self._ddirty = self._tdirty = False

        # The indirect dispatch count records actual coarse survivors, including
        # refinements that yield no final detection. Read after completion;
        # no extra submission or host decision is needed.
        self._gpairs += idx.shape[0] * idx.shape[1]
        self._gtrig += self._gpu.last_refinements
        return idx, val

    def set_coarse_threshold(self, value):
        """Set the coarse threshold directly, bypassing the model.

        The coarse pass reports one number per pair -- the maximum of the
        band-limited correlation -- and this is what it is compared against.
        Above it the pair gets the full filter; below it the pair is
        dismissed. That is the whole decision.

        Autotuning exists to choose this number for a false-dismissal budget,
        using the reference profile model. A caller who knows what threshold
        they want does not: set it here and no table is consulted, no
        reference is required when the band is explicitly set, and nothing is modelled. The guarantee becomes
        whatever the caller's own threshold implies, which is the honest
        trade for not asking the library to promise a budget.

        Pass None to go back to the model.
        """
        if value is None:
            self._cal_thr = None
            self._thr_applied = False
            if self._mf is not None:
                self._mf.set_threshold(-1.0)
            return
        value = float(value)
        if not np.isfinite(value) or value < 0 or value > float(np.finfo(np.float32).max):
            raise ValueError("coarse threshold must be finite nonnegative float32, or None")
        if self._pinned is None:
            raise ValueError("an explicit coarse threshold requires an explicit band")
        self._cal_thr = value
        self._thr_applied = True
        if self._mf is not None:
            self._mf.set_threshold(float(value))

    def set_first_stage(self, snr):
        """Calibrate the first stage against `snr` rather than the threshold.

        Final triggers are still cut at the threshold passed to :meth:`run`;
        this sets only where the cheap first pass decides a full
        reconstruction is needed.  Lower it to run the first stage more
        conservatively, at the cost of reconstructing more often.

        The threshold is computed from the profile at this SNR. An unresolved
        budget raises at execution. Band and taps stay fixed. An explicit
        coarse threshold takes precedence over this setting.

        Pass ``None`` or a non-positive value to use the constructor's SNR.
        """
        self._fs_snr = float(snr) if snr is not None and float(snr) > 0 else None
        self._thr_applied = False
        if self._mf is not None and self._cal_thr is None:
            self._mf.set_threshold(-1.0)

    def set_reference(self, power):
        """Set the reference SNR distribution.

        ``power`` is a real frequency series of length ``n``: the expected
        power of the filter *output* in each bin.  Only its shape matters, as
        the total is divided out.

        By default each template's band fraction is
        computed from the template itself, which assumes its own power
        distribution is the distribution of the SNR it produces.  That holds
        only when the data is white and the template whitened.  A broadband
        ratio filter reconstructing a low-frequency signal breaks it badly --
        the coarse threshold would read the filter, not the signal.

        The profile must describe every template in this plan. Heterogeneous
        banks may need separate reference groups: equal in-band fractions
        do not imply equal scalloping or dismissal. Pass ``None`` to use each
        template's own band fraction with an explicit coarse threshold.
        Changing the reference refreshes already-loaded coarse templates.
        """
        if power is not None:
            p = np.ascontiguousarray(_from_any(power), dtype=np.float32)
            if p.shape != (self.n,):
                raise ValueError("reference must be a one-dimensional array of length %d" % self.n)
            if not np.isfinite(p).all() or np.any(p < 0) or not np.any(p > 0):
                raise ValueError("reference must be finite, nonnegative, with positive total power")
        if self._gpu is not None:
            # Calibration and scaled coarse templates depend on the reference,
            # even when the template spectra themselves have not changed.
            self._gcal = None
            self._tdirty = True
        self._thr_applied = False
        if self._mf is not None and self._cal_thr is None:
            self._mf.set_threshold(-1.0)
        if power is None:
            self._pending_ref = None
            if self._mf is not None:
                self._mf.set_reference(None)
            return
        self._pending_ref = p
        if self._mf is not None:
            self._mf.set_reference(p)


    @property
    def config(self):
        """Selected or explicitly pinned ``(band, taps)``."""
        if self._pinned is not None:
            return self._pinned
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
            return self._gtrig / self._gpairs if self._gpairs else 0.0
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
