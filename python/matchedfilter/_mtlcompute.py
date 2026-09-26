"""Dispatching the Metal kernels, with ctypes over the Objective-C runtime.

No PyObjC and no compiled helper: the wheel carries kernels, and the only
thing it needs from the machine is Metal itself, which every Mac has.

The calling convention differs from Vulkan and the difference is silent if
got wrong. Slang lowers the entry point's uniform parameters to a CONSTANT
BUFFER at index 0 and shifts the storage buffers to 1..4, where SPIR-V puts
the storage buffers at 0..3 and the uniforms in push constants. The struct
is the same seven 32-bit fields in the same order.

UNTESTED ON LINUX by construction -- there is no Apple hardware on the
development machine, so every line here is exercised only by the macOS CI
job. It is written to fail loudly rather than plausibly.
"""
import ctypes
import pathlib
import sys
from contextlib import contextmanager
from functools import wraps

import numpy as np
from ._shared import empty_shared, shared_buffer, shared_key, write_input

_HERE = pathlib.Path(__file__).resolve().parent
_METAL_DIR = _HERE / "metal"
_MANIFEST = _HERE / "spirv" / "manifest.json"

_manifest_cache = None


def _manifest():
    """The build manifest, shared with the SPIR-V backend.

    Both backends are generated from the same Slang source with the same
    staging cap, so the recorded threadgroup-memory figure is the same
    number for either -- there is no second manifest to keep in step.
    """
    global _manifest_cache
    if _manifest_cache is None:
        import json
        _manifest_cache = (json.loads(_MANIFEST.read_text())
                           if _MANIFEST.is_file() else {})
    return _manifest_cache

#: MTLResourceStorageModeShared: one allocation both CPU and GPU can see.
#: Apple silicon is unified memory, so this is the natural mode rather than
#: a compromise -- there is no separate device heap to stage into.
_STORAGE_SHARED = 0

#: The per-bin table aliases the exchange staging inside the kernel, so the
#: kernel cannot hold more bins than that. Identical to the SPIR-V build --
#: same Slang source, same limit -- and the split below is how both stay
#: correct past it rather than quietly writing off the end of the table.
_MAX_BINS = 2048


from ._errors import UnsupportedSize      # noqa: F401  (re-export)
from ._gpu_cache import InputUploads


#: Points per thread, which is also how many threads carry a transform:
#: WG = n / R. Vulkan bakes this into the SPIR-V and the host never needs
#: it; Metal is dispatched with an explicit threadgroup size, so the host
#: has to agree with the kernel. Getting it wrong here does not fail to
#: launch -- it launches the wrong shape.
#:
#: Mirrors tools/build_spirv.py RADIX, which is what compiled them.
_RADIX = {32768: 32, 65536: 64}


def _radix(n):
    return _RADIX.get(n, 16)


class MetalError(RuntimeError):
    pass


class _ObjC:
    """The handful of Objective-C entry points this needs.

    Each message signature gets its OWN function pointer. Reusing one
    objc_msgSend and reassigning argtypes is the classic way to get silent
    corruption on arm64, where the calling convention depends on the
    argument types.
    """

    def __init__(self):
        self.objc = ctypes.CDLL("/usr/lib/libobjc.dylib")
        self.metal = ctypes.CDLL(
            "/System/Library/Frameworks/Metal.framework/Metal")
        self.foundation = ctypes.CDLL(
            "/System/Library/Frameworks/Foundation.framework/Foundation")
        self.objc.sel_registerName.restype = ctypes.c_void_p
        self.objc.sel_registerName.argtypes = [ctypes.c_char_p]
        self.objc.objc_getClass.restype = ctypes.c_void_p
        self.objc.objc_getClass.argtypes = [ctypes.c_char_p]

    @contextmanager
    def autorelease_pool(self):
        push = self.objc.objc_autoreleasePoolPush
        push.restype = ctypes.c_void_p
        push.argtypes = []
        pop = self.objc.objc_autoreleasePoolPop
        pop.restype = None
        pop.argtypes = [ctypes.c_void_p]
        pool = push()
        try:
            yield
        finally:
            pop(pool)

    def sel(self, name):
        return self.objc.sel_registerName(name)

    def send(self, restype, argtypes):
        """A correctly-typed objc_msgSend for one signature."""
        fn = ctypes.cast(self.objc.objc_msgSend,
                         ctypes.CFUNCTYPE(restype, ctypes.c_void_p,
                                          ctypes.c_void_p, *argtypes))
        return fn

    def call(self, obj, selector, restype=ctypes.c_void_p, args=(),
             argtypes=()):
        return self.send(restype, argtypes)(obj, self.sel(selector), *args)

    def nsstring(self, text):
        cls = self.objc.objc_getClass(b"NSString")
        return self.call(cls, b"stringWithUTF8String:",
                         args=(text.encode("utf-8"),),
                         argtypes=(ctypes.c_char_p,))

    def to_str(self, ns):
        if not ns:
            return ""
        ptr = self.call(ns, b"UTF8String")
        return ctypes.cast(ptr, ctypes.c_char_p).value.decode("utf-8", "replace") \
            if ptr else ""


class _MTLSize(ctypes.Structure):
    _fields_ = [("width", ctypes.c_ulong),
                ("height", ctypes.c_ulong),
                ("depth", ctypes.c_ulong)]


class _Buffer:
    """A shared-storage buffer, mapped for the lifetime of the object."""

    def __init__(self, ctx, nbytes):
        self.ctx = ctx
        self.nbytes = max(int(nbytes), 16)
        self.handle = ctx.o.call(
            ctx.device, b"newBufferWithLength:options:",
            args=(self.nbytes, _STORAGE_SHARED),
            argtypes=(ctypes.c_ulong, ctypes.c_ulong))
        if not self.handle:
            raise MetalError("newBufferWithLength failed for %d bytes" % nbytes)
        self.ptr = ctx.o.call(self.handle, b"contents")

    def write(self, array):
        flat = np.ascontiguousarray(array)
        if flat.nbytes > self.nbytes:
            raise MetalError("write of %d into a %d-byte buffer"
                             % (flat.nbytes, self.nbytes))
        ctypes.memmove(self.ptr, flat.ctypes.data, flat.nbytes)

    def read(self, dtype, count):
        out = np.empty(count, dtype=dtype)
        ctypes.memmove(out.ctypes.data, self.ptr, out.nbytes)
        return out

    def destroy(self):
        if self.handle:
            self.ctx.o.call(self.handle, b"release")
            self.handle = None


def describe_error(o, err):
    """Everything the NSError carries, not only its one-line summary.

    A pipeline that fails to build reports "Compilation failed" as its
    localizedDescription and puts the actual back-end diagnostics in
    userInfo, so the short form names the failure without ever saying
    what it was -- which is exactly the report that cost a CI round
    trip. `description` dumps the whole object, userInfo included.
    """
    if not err or not err.value:
        return "no error object"
    parts = []
    for sel in (b"localizedDescription", b"localizedFailureReason",
                b"localizedRecoverySuggestion", b"description"):
        try:
            got = o.to_str(o.call(err.value, sel))
        except Exception:                      # selector not implemented
            continue
        got = (got or "").strip()
        if got and not any(got in seen for seen in parts):
            parts.append(got)
    domain = o.to_str(o.call(err.value, b"domain"))
    code = int(o.call(err.value, b"code", restype=ctypes.c_long))
    parts.append("[domain=%s code=%d]" % (domain or "?", code))
    return " | ".join(parts)



def _autoreleased(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.o.autorelease_pool():
            return method(self, *args, **kwargs)
    return call


class Context(InputUploads):
    """One Metal device, its queue, and the pipelines built on it."""

    def __init__(self, index=0):
        if sys.platform != "darwin":
            raise MetalError("Metal is only available on macOS")
        self.o = _ObjC()
        self.device = self.queue = None
        self._pipelines = {}
        self._batches = {}
        self._hier = {}
        try:
            self._initialize(index)
        except Exception:
            self.destroy()
            raise

    @_autoreleased
    def _initialize(self, index):
        self.o.metal.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p
        # Enumerate rather than ask for the "system default", which is the
        # device recommended for RENDERING and is nil with no display
        # attached. Compute does not need one.
        from . import _metal
        found = _metal._all_devices(self.o.objc, self.o.metal)
        if not found:
            one = self.o.metal.MTLCreateSystemDefaultDevice()
            found = [one] if one else []
        if index < 0 or index >= len(found):
            for handle in found:
                self.o.call(handle, b"release", restype=None)
            raise MetalError(
                "no Metal device with index %d (found %d); "
                "MTLCopyAllDevices is the enumeration and "
                "MTLCreateSystemDefaultDevice needs a display"
                % (index, len(found)))
        self.device = found[index]
        for i, handle in enumerate(found):
            if i != index:
                self.o.call(handle, b"release", restype=None)
        self.name = self.o.to_str(self.o.call(self.device, b"name"))
        self.queue = self.o.call(self.device, b"newCommandQueue")
        #: Device-only seconds for the last dispatch, see _record_gpu_time.
        self.last_gpu_time = 0.0
        if not self.queue:
            raise MetalError("newCommandQueue failed")
        self.max_shared_memory = int(self.o.call(
            self.device, b"maxThreadgroupMemoryLength", restype=ctypes.c_ulong))
        self._pipelines = {}
        self._batches = {}
        self._hier = {}
        self._uploaded = {"data": {}, "tmpl": {}}

    # ---- kernels ----------------------------------------------------------
    def _library(self, stem):
        """A compiled .metallib if one shipped, else compile the source.

        The library is what a macOS wheel carries, built by Apple's compiler
        on the macOS runner. The .metal source travels as well so a wheel
        built elsewhere -- or one whose library is stale -- still runs,
        paying a compile on first use rather than refusing.
        """
        lib_path = _METAL_DIR / (stem + ".metallib")
        if lib_path.is_file():
            url_cls = self.o.objc.objc_getClass(b"NSURL")
            url = self.o.call(url_cls, b"fileURLWithPath:",
                              args=(self.o.nsstring(str(lib_path)),),
                              argtypes=(ctypes.c_void_p,))
            err = ctypes.c_void_p()
            lib = self.o.call(self.device, b"newLibraryWithURL:error:",
                              args=(url, ctypes.byref(err)),
                              argtypes=(ctypes.c_void_p, ctypes.c_void_p))
            if lib:
                return lib
        src_path = _METAL_DIR / (stem + ".metal")
        if not src_path.is_file():
            raise MetalError("no Metal kernel for %s (looked for %s and %s)"
                             % (stem, lib_path.name, src_path.name))
        err = ctypes.c_void_p()
        lib = self.o.call(self.device, b"newLibraryWithSource:options:error:",
                          args=(self.o.nsstring(src_path.read_text()), None,
                                ctypes.byref(err)),
                          argtypes=(ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p))
        if not lib:
            raise MetalError("could not build a Metal library from %s: %s"
                             % (src_path.name, self._error(err)))
        return lib

    def _error(self, err):
        return describe_error(self.o, err)

    def _stem(self, n, entry):
        """The kernel variant this device can actually hold.

        Apple caps threadgroup memory at 32 KB. The tuned staging asks for
        64 KB at n=16384 and exactly 32 KB at n=8192, so on Apple the
        preferred build cannot create a pipeline at all -- and it reports
        that as "Compilation failed", which names nothing. Choosing the
        portable build here turns a dead end into a slower kernel.
        """
        # One stem per entry point. This was a two-way choice -- fusedTierB
        # or "the other one" -- which silently sends every new entry to the
        # gated library, where its function does not exist. The same
        # assumption was in the build script's artifact naming.
        if entry == "packCoarse":
            return "pack_coarse"
        if entry == "seriesForward":
            return "forward_%d" % n
        base = "%s_%d" % ({"fusedTierB": "tierb",
                           "compactPairs": "compact",
                           "refineListed": "refine"}[entry], n)
        info = _manifest().get("modules", {}).get(str(n), {})
        # The Metal column. Metal is built against its own staging cap
        # -- Apple and the Radeon want opposite answers -- so reading
        # the Vulkan "lds_bytes" here would compare this device's limit
        # against a number no Metal kernel was built with, and pick the
        # portable variant at sizes that do not need it.
        need = info.get("metal_lds_bytes", info.get("lds_bytes", 0))
        if need <= self.max_shared_memory:
            return base
        alt = base + "_lds32"
        if not any((_METAL_DIR / (alt + ext)).is_file()
                   for ext in (".metallib", ".metal")):
            raise MetalError(
                "n=%d needs %d KB of threadgroup memory, %s offers %d KB, "
                "and no portable build was shipped for it"
                % (n, need // 1024, self.name,
                   self.max_shared_memory // 1024))
        return alt

    def _pipeline_sized(self, stem, fn, want):
        """Rebuild the pipeline having told the compiler the group size.

        maxTotalThreadsPerThreadgroup is an INPUT to the descriptor form, not
        only a report. Left alone the compiler optimises for occupancy and
        stops wherever the registers land -- 576 for the n=16384 kernel on an
        M2, against the 1024 it is dispatched at, so that length was refused
        outright. Asked for 1024 it delivers 1024, spilling if it must.

        ONLY when the default is short, which is the part worth stating.
        Declaring it unconditionally also works, in the sense that every
        pipeline builds and reports the size asked for -- and it changed the
        answer at n=4096 on an M2, where the default allows 448 and nothing
        needed asking. test_run_series_agrees_with_the_cpu failed
        deterministically, three runs out of three, and passed again the
        moment the descriptor was dropped. Constraining a kernel that did not
        need constraining is not free, so it is not done.

        Measured on an M2:

            kernel               needs   default   declared
            tierb_4096             256       448        --    (left alone)
            tierb_8192_lds32       512       512        --    (left alone)
            tierb_16384_lds32     1024       576      1024
        """
        desc = self.o.call(
            self.o.call(self.o.objc.objc_getClass(
                b"MTLComputePipelineDescriptor"), b"alloc"), b"init")
        try:
            self.o.call(desc, b"setComputeFunction:", restype=None,
                        args=(fn,), argtypes=(ctypes.c_void_p,))
            self.o.call(desc, b"setMaxTotalThreadsPerThreadgroup:", restype=None,
                        args=(want,), argtypes=(ctypes.c_ulong,))
            err = ctypes.c_void_p()
            pso = self.o.call(
                self.device,
                b"newComputePipelineStateWithDescriptor:options:reflection:error:",
                args=(desc, 0, None, ctypes.byref(err)),
                argtypes=(ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p,
                          ctypes.c_void_p))
        finally:
            self.o.call(desc, b"release", restype=None)
        if not pso:
            raise MetalError(
                "%s needs a %d-thread threadgroup and asking for one failed: "
                "%s" % (stem, want, self._error(err)))
        return pso, int(self.o.call(pso, b"maxTotalThreadsPerThreadgroup",
                                    restype=ctypes.c_ulong))

    @_autoreleased
    def pipeline(self, n, entry="fusedTierB"):
        key = (n, entry)
        if key in self._pipelines:
            return self._pipelines[key]
        stem = self._stem(n, entry)
        lib = self._library(stem)
        fn = pso = None
        try:
            fn = self.o.call(lib, b"newFunctionWithName:",
                             args=(self.o.nsstring(entry),),
                             argtypes=(ctypes.c_void_p,))
            if not fn:
                raise MetalError("no function %r in %s" % (entry, stem))
            want = n // _radix(n)
            err = ctypes.c_void_p()
            pso = self.o.call(self.device,
                              b"newComputePipelineStateWithFunction:error:",
                              args=(fn, ctypes.byref(err)),
                              argtypes=(ctypes.c_void_p, ctypes.c_void_p))
            if not pso:
                raise MetalError("could not build a pipeline for %s: %s"
                                 % (stem, self._error(err)))
            limit = int(self.o.call(pso, b"maxTotalThreadsPerThreadgroup",
                                    restype=ctypes.c_ulong))
            if limit < want:
                self.o.call(pso, b"release", restype=None)
                pso = None
                pso, limit = self._pipeline_sized(stem, fn, want)
            if limit < want:
                raise UnsupportedSize(
                    "n=%d needs a %d-thread threadgroup and this pipeline allows "
                    "%d on %s even when asked for %d; use a shorter transform or "
                    "device='cpu'" % (n, want, limit, self.name, want))
            self._pipelines[key] = pso
            result, pso = pso, None  # ownership transferred to the cache
            return result

        finally:
            for obj in (pso, fn, lib):
                if obj:
                    self.o.call(obj, b"release", restype=None)

    # ---- dispatch ---------------------------------------------------------
    def _record_gpu_time(self, cmd):
        """Device-only duration of the command buffer just completed.

        Metal builds its encoders per dispatch, so there is no recording to
        replay the way the Vulkan path times device work. GPUEndTime and
        GPUStartTime give the same thing more directly: the window the GPU
        actually spent, with the host's marshalling left out. Cost tuning
        needs that -- timing the whole call instead adds a per-call constant
        to every configuration, which compresses the ratios it is trying to
        measure and made adjacent margins come out non-monotonic on Vulkan.

        Only meaningful after waitUntilCompleted.
        """
        t0 = self.o.call(cmd, b"GPUStartTime", restype=ctypes.c_double)
        t1 = self.o.call(cmd, b"GPUEndTime", restype=ctypes.c_double)
        self.last_gpu_time = float(t1) - float(t0)

    def empty_shared(self, shape, dtype=np.complex64):
        return empty_shared(self, _Buffer, shape, dtype)

    @_autoreleased
    def forward(self, n, series, starts, spectra, *, defer=False):
        pso = self.pipeline(n, "seriesForward")
        buffers = [shared_buffer(a, self) for a in (series, starts, spectra)]
        if any(b is None for b in buffers):
            raise ValueError("forward buffers must belong to this GPU context")
        cmd = self.o.call(self.queue, b"commandBuffer")
        enc = self.o.call(cmd, b"computeCommandEncoder")
        self.o.call(enc, b"setComputePipelineState:", restype=None,
                    args=(pso,), argtypes=(ctypes.c_void_p,))
        params = ctypes.c_uint32(series.size)
        self.o.call(enc, b"setBytes:length:atIndex:", restype=None,
                    args=(ctypes.byref(params), 4, 0),
                    argtypes=(ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong))
        for slot, buf in enumerate(buffers, start=1):
            self.o.call(enc, b"setBuffer:offset:atIndex:", restype=None,
                        args=(buf.handle, 0, slot),
                        argtypes=(ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong))
        self.o.call(enc, b"dispatchThreadgroups:threadsPerThreadgroup:",
                    restype=None,
                    args=(_MTLSize(spectra.shape[0], 1, 1), _MTLSize(n // _radix(n), 1, 1)),
                    argtypes=(_MTLSize, _MTLSize))
        self.o.call(enc, b"endEncoding", restype=None)
        if defer:
            self.o.call(cmd, b"retain")
            self._pending_metal = (cmd, buffers)
            return
        self.o.call(cmd, b"commit", restype=None)
        self.o.call(cmd, b"waitUntilCompleted", restype=None)
        self._check_completed(cmd)

    def _command_buffer(self):
        pending = getattr(self, "_pending_metal", None)
        if pending is None:
            return self.o.call(self.queue, b"commandBuffer")
        self._pending_metal = None
        self._forward_inflight = pending
        return pending[0]

    def cancel_forward(self):
        for name in ("_pending_metal", "_forward_inflight"):
            pending = getattr(self, name, None)
            if pending is not None:
                self.o.call(pending[0], b"release", restype=None)
                setattr(self, name, None)

    @_autoreleased
    def peaks(self, n, data, tmpl, binsize=None, threshold=0.0, window=None,
              upload_data=True, upload_tmpl=True):
        """Peak index and complex value per (data, template, bin).

        The same contract as the Vulkan path: bins counted from `start`, a
        bin nothing clears reported as index -1 with a zero value.
        """
        nd, nt = data.shape[0], tmpl.shape[0]
        lo, hi = (0, n) if window is None else (int(window[0]), int(window[1]))
        lo, hi = max(0, min(lo, n)), max(0, min(hi, n))
        if lo >= hi:
            raise ValueError("empty window (%d, %d)" % (lo, hi))
        binsize = n if binsize is None else int(binsize)
        nbins = -(-(hi - lo) // binsize)
        if nbins > _MAX_BINS:
            # Bins are contiguous in the window, so cutting the window on a
            # bin boundary cuts the bins exactly and the pieces concatenate.
            span = _MAX_BINS * binsize
            pi, pv = [], []
            for a in range(lo, hi, span):
                i2, v2 = self.peaks(n, data, tmpl, binsize=binsize,
                                    threshold=threshold,
                                    window=(a, min(a + span, hi)),
                                    upload_data=upload_data,
                                    upload_tmpl=upload_tmpl)
                pi.append(i2)
                pv.append(v2)
                upload_data = upload_tmpl = False    # already on the device
            return np.concatenate(pi, axis=2), np.concatenate(pv, axis=2)
        shift = (binsize.bit_length() - 1) if binsize & (binsize - 1) == 0 else -1
        t2 = float(threshold) ** 2 if threshold > 0 else 0.0

        key = (n, nd, nt, nbins)
        key += (shared_key(data, self), shared_key(tmpl, self))
        upload_data, upload_tmpl, dsig, tsig = self._input_uploads(
            key, data, tmpl, upload_data, upload_tmpl)
        batch = self._batches.get(key)
        if batch is None:
            incoming = [b for a in (data, tmpl)
                        if (b := shared_buffer(a, self)) is not None]
            estimate = 8*n*(nd+nt) + 12*nd*nt*nbins
            estimate -= sum(a.nbytes for a in (data, tmpl)
                            if shared_buffer(a, self) is not None)
            self._cache_room(estimate, incoming=incoming)
            out = nd * nt * nbins
            batch = (shared_buffer(data, self) or _Buffer(self, nd * n * 8),
                     shared_buffer(tmpl, self) or _Buffer(self, nt * n * 8),
                     _Buffer(self, out * 4), _Buffer(self, out * 8))
            self._batches[key] = batch
            upload_data = upload_tmpl = True
        self._cache_touch("flat", key)
        b_data, b_tmpl, b_idx, b_val = batch
        if upload_data:
            write_input(b_data, data)
            self._uploaded["data"][key] = dsig
        if upload_tmpl:
            write_input(b_tmpl, tmpl)
            self._uploaded["tmpl"][key] = tsig

        pso = self.pipeline(n)
        cmd = self._command_buffer()
        enc = self.o.call(cmd, b"computeCommandEncoder")
        self.o.call(enc, b"setComputePipelineState:", restype=None,
                    args=(pso,), argtypes=(ctypes.c_void_p,))

        # Index 0 is the uniform block; the storage buffers follow.
        params = (ctypes.c_uint32 * 7)(
            nt, lo, hi, binsize, shift & 0xFFFFFFFF, nbins,
            int(np.float32(t2).view(np.uint32)))
        self.o.call(enc, b"setBytes:length:atIndex:", restype=None,
                    args=(ctypes.byref(params), ctypes.sizeof(params), 0),
                    argtypes=(ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong))
        for slot, buf in enumerate((b_data, b_tmpl, b_idx, b_val), start=1):
            self.o.call(enc, b"setBuffer:offset:atIndex:", restype=None,
                        args=(buf.handle, 0, slot),
                        argtypes=(ctypes.c_void_p, ctypes.c_ulong,
                                  ctypes.c_ulong))

        grid = _MTLSize(nd * nt, 1, 1)
        group = _MTLSize(n // _radix(n), 1, 1)
        self.o.call(enc, b"dispatchThreadgroups:threadsPerThreadgroup:",
                    restype=None, args=(grid, group),
                    argtypes=(_MTLSize, _MTLSize))
        self.o.call(enc, b"endEncoding", restype=None)
        self.o.call(cmd, b"commit", restype=None)
        self.o.call(cmd, b"waitUntilCompleted", restype=None)
        self._record_gpu_time(cmd)

        self._check_completed(cmd)

        out = nd * nt * nbins
        idx = b_idx.read(np.int32, out).reshape(nd, nt, nbins)
        val = b_val.read(np.float32, out * 2).view(
            np.complex64).reshape(nd, nt, nbins)
        return idx, val

    # ---- hierarchical -----------------------------------------------------
    @_autoreleased
    def hier_peaks(self, n, band, data, tmpl, ct0, raw_thr,
                   binsize=None, threshold=0.0, window=None,
                   upload_data=True, upload_tmpl=True):
        """The whole hierarchical filter in ONE command buffer.

        Coarse correlation, survivor compaction, then listed refinement.
        Shared input uses a preceding GPU coarse-band extraction dispatch.
        The survivor count stays on the device through indirect dispatch.
        """
        nd, nt = data.shape[0], tmpl.shape[0]
        pairs = nd * nt
        lo, hi = (0, n) if window is None else (int(window[0]), int(window[1]))
        lo, hi = max(0, min(lo, n)), max(0, min(hi, n))
        if lo >= hi:
            raise ValueError("empty window (%d, %d)" % (lo, hi))
        binsize = n if binsize is None else int(binsize)
        nbins = -(-(hi - lo) // binsize)
        if nbins > _MAX_BINS:
            span = _MAX_BINS * binsize
            pi, pv = [], []
            for a in range(lo, hi, span):
                i2, v2 = self.hier_peaks(n, band, data, tmpl, ct0, raw_thr, binsize=binsize,
                                         threshold=threshold,
                                         window=(a, min(a + span, hi)),
                                         upload_data=upload_data,
                                         upload_tmpl=upload_tmpl)
                pi.append(i2)
                pv.append(v2)
                upload_data = upload_tmpl = False     # already on the device
            return np.concatenate(pi, axis=2), np.concatenate(pv, axis=2)
        shift = (binsize.bit_length() - 1) if binsize & (binsize - 1) == 0 else -1
        t2 = float(threshold) ** 2 if threshold > 0 else 0.0

        key = (n, band, nd, nt, nbins)
        key += (shared_key(data, self), shared_key(tmpl, self))
        upload_data, upload_tmpl, dsig, tsig = self._input_uploads(
            key, data, tmpl, upload_data, upload_tmpl)
        bufs = self._hier.get(key)
        if bufs is None:
            incoming = [b for a in (data, tmpl)
                        if (b := shared_buffer(a, self)) is not None]
            estimate = 8*n*(nd+nt) + 8*band*(nd+nt) + nd*nt*(16+12*nbins) + 12
            estimate -= sum(a.nbytes for a in (data, tmpl)
                            if shared_buffer(a, self) is not None)
            self._cache_room(estimate, incoming=incoming)
            bufs = {
                "data":  shared_buffer(data, self) or _Buffer(self, nd * n * 8),
                "tmpl":  shared_buffer(tmpl, self) or _Buffer(self, nt * n * 8),
                "cdata": _Buffer(self, nd * band * 8),
                "ct0":   _Buffer(self, nt * band * 8),
                "cidx":  _Buffer(self, pairs * 4),
                "cval":  _Buffer(self, pairs * 8),
                # Compacted survivors and the indirect threadgroup count.
                # args is [groupsX, 1, 1]; compactPairs bumps [0] atomically,
                # so the count stays on the device and this is still one
                # command buffer with no host in the loop.
                "surv":  _Buffer(self, pairs * 4),
                "args":  _Buffer(self, 12),
                "idx":   _Buffer(self, nd * nt * nbins * 4),
                "val":   _Buffer(self, nd * nt * nbins * 8),
            }
            self._hier[key] = bufs
            # Fresh buffers hold nothing, whatever the caller's dirty flags
            # say. Trusting them here is exactly how the Vulkan path once
            # served a previous call's data out of a newly allocated buffer,
            # and every index came back -1.
            upload_data = upload_tmpl = True
        self._cache_touch("hier", key)
        if upload_data:
            write_input(bufs["data"], data)
            if shared_buffer(data, self) is None:
                bufs["cdata"].write(np.ascontiguousarray(data[:, :band],
                                                         np.complex64))
            self._uploaded["data"][key] = dsig
        if upload_tmpl:
            write_input(bufs["tmpl"], tmpl)
            bufs["ct0"].write(np.ascontiguousarray(ct0, np.complex64))
            self._uploaded["tmpl"][key] = tsig

        coarse = self.pipeline(band)
        compact = self.pipeline(n, "compactPairs")
        refine = self.pipeline(n, "refineListed")

        # Pairs that do not survive are never visited, so their -1 has to be
        # there already. Metal has no fill on a compute encoder, and writing
        # from the host is a 3 MB memcpy per call at 512x512 -- so the
        # clear rides along in the compaction kernel, which walks every pair
        # anyway. Only args needs a host write, and it is twelve bytes.
        bufs["args"].write(np.array([0, 1, 1], dtype=np.uint32))

        cmd = self._command_buffer()
        enc = self.o.call(cmd, b"computeCommandEncoder")

        def dispatch(pso, params, names, width, groups=pairs, tg=None):
            # tg is the kernel's own numthreads. Deriving it from width
            # works for the transform kernels, where it is width//R, and
            # is wrong for compactPairs, which is numthreads(256) and has
            # no transform length at all.
            tg = (width // _radix(width)) if tg is None else tg
            self.o.call(enc, b"setComputePipelineState:", restype=None,
                        args=(pso,), argtypes=(ctypes.c_void_p,))
            blk = (ctypes.c_uint32 * len(params))(*params)
            self.o.call(enc, b"setBytes:length:atIndex:", restype=None,
                        args=(ctypes.byref(blk), ctypes.sizeof(blk), 0),
                        argtypes=(ctypes.c_void_p, ctypes.c_ulong,
                                  ctypes.c_ulong))
            for slot, nm in enumerate(names, start=1):
                self.o.call(enc, b"setBuffer:offset:atIndex:", restype=None,
                            args=(bufs[nm].handle, 0, slot),
                            argtypes=(ctypes.c_void_p, ctypes.c_ulong,
                                      ctypes.c_ulong))
            if groups is None:
                # Indirect: the threadgroup count is read from args on the
                # device, so the survivor count never crosses to the host.
                self.o.call(
                    enc,
                    b"dispatchThreadgroupsWithIndirectBuffer:"
                    b"indirectBufferOffset:threadsPerThreadgroup:",
                    restype=None,
                    args=(bufs["args"].handle, 0,
                          _MTLSize(tg, 1, 1)),
                    argtypes=(ctypes.c_void_p, ctypes.c_ulong, _MTLSize))
            else:
                self.o.call(enc, b"dispatchThreadgroups:threadsPerThreadgroup:",
                            restype=None,
                            args=(_MTLSize(groups, 1, 1),
                                  _MTLSize(tg, 1, 1)),
                            argtypes=(_MTLSize, _MTLSize))

        def bits(x):
            return int(np.float32(x).view(np.uint32))

        # Coarse even: ONE bin over the whole coarse span, so the reported
        # peak IS the maximum -- which is all the gate needs.
        if shared_buffer(data, self) is not None:
            dispatch(self.pipeline(4096, "packCoarse"),
                     (n, band, nd*band, 0), ("data", "cdata"), 4096,
                     groups=(nd*band + 255)//256, tg=256)

        dispatch(coarse,
                 (nt, 0, band, band, band.bit_length() - 1, 1, 0),
                 ("cdata", "ct0", "cidx", "cval"), band)

        # Compaction: one THREAD per pair, gathering the survivors and
        # writing the -1 for everyone else. The refine used to launch a
        # threadgroup for every pair so that each could read the coarse
        # value and exit; on Vulkan that was 1.394 ms of a 2.437 ms call.
        dispatch(compact,
                 (pairs, bits(raw_thr), nbins),
                 ("cval", "surv", "args", "idx", "val"), 0,
                 groups=(pairs + 255) // 256, tg=256)

        # The refine, over the compacted list, sized on the device.
        dispatch(refine,
                 (nt, lo, hi, binsize, shift & 0xFFFFFFFF, nbins, bits(t2)),
                 ("data", "tmpl", "idx", "val", "surv"), n, groups=None)

        self.o.call(enc, b"endEncoding", restype=None)
        self.o.call(cmd, b"commit", restype=None)
        self.o.call(cmd, b"waitUntilCompleted", restype=None)
        self._record_gpu_time(cmd)
        self._check_completed(cmd)

        out = nd * nt * nbins
        idx = bufs["idx"].read(np.int32, out).reshape(nd, nt, nbins)
        val = bufs["val"].read(np.float32, out * 2).view(
            np.complex64).reshape(nd, nt, nbins)
        self.last_refinements = int(bufs["args"].read(np.uint32, 1)[0])
        return idx, val

    def _check_completed(self, cmd):
        """A command buffer that did not complete, said so.

        The GPU reports failure by status rather than by raising, so without
        this a kernel that never ran returns whatever the output buffer
        happened to hold -- zeros, or the previous call's answer.
        """
        status = int(self.o.call(cmd, b"status", restype=ctypes.c_ulong))
        if status == 4:                       # MTLCommandBufferStatusCompleted
            return
        err = self.o.call(cmd, b"error")
        raise MetalError("dispatch did not complete (status %d): %s"
                         % (status, describe_error(
                             self.o, ctypes.c_void_p(err)) if err
                            else "no error object"))

    def _evict_record(self, kind, key, keep_storage=None):
        cache = self._batches if kind == 'flat' else self._hier
        batch = cache.pop(key)
        for buf in (batch.values() if isinstance(batch, dict) else batch):
            buf.destroy()
        for resident in self._uploaded.values():
            resident.pop(key, None)

    def clear_cache(self):
        for batch in self._batches.values():
            for buf in batch:
                buf.destroy()
        for bufs in self._hier.values():
            for buf in bufs.values():
                buf.destroy()
        self._batches.clear()
        self._hier.clear()
        self._uploaded = {"data": {}, "tmpl": {}}
        self._cache_order = {}

    def destroy(self):
        if getattr(self, "device", None) is None:
            return
        self.cancel_forward()
        self.clear_cache()
        for pipeline in self._pipelines.values():
            self.o.call(pipeline, b"release", restype=None)
        self._pipelines.clear()
        if self.queue:
            self.o.call(self.queue, b"release", restype=None)
            self.queue = None
        self.o.call(self.device, b"release", restype=None)
        self.device = None

    def __del__(self):
        """Release the device buffers when the context is dropped.

        Metal does not hold the file descriptors Vulkan does, so this is not
        the leak that exhausted RLIMIT_NOFILE -- but a dropped context still
        held its batch and hierarchical buffers until the process ended, and
        the two backends should not differ on whether going out of scope
        frees anything.
        """
        try:
            self.destroy()
        except Exception:
            pass
