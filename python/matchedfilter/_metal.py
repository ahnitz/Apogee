"""Finding Apple GPUs, through Metal, with ctypes.

Detection is separated from execution on purpose. The kernels ship as Metal
and there is no Metal runtime yet, so nothing could report an Apple GPU at
all -- which made "no GPU on this machine" the answer on a Mac that has one,
and made a macOS CI run unable to say anything about the hardware it was
running on.

This answers the narrower question that can be answered today: is there a
Metal device, and what is it? That is what decides whether writing the
runtime is worth it, and on a hosted runner it is genuinely in doubt --
those are virtual machines, and a guest is not guaranteed a GPU.

Calls MTLCreateSystemDefaultDevice and reads the device's name through the
Objective-C runtime. No PyObjC, nothing to install.
"""
import ctypes
import sys

_METAL = "/System/Library/Frameworks/Metal.framework/Metal"
_OBJC = "/usr/lib/libobjc.dylib"


def _nsstring(objc, obj, selector):
    """[obj selector] as a Python str, for selectors returning NSString."""
    sel = objc.sel_registerName(selector)
    ns = objc.objc_msgSend(obj, sel)
    if not ns:
        return ""
    utf8 = objc.sel_registerName(b"UTF8String")
    ptr = objc.objc_msgSend(ns, utf8)
    return ctypes.cast(ptr, ctypes.c_char_p).value.decode("utf-8", "replace") \
        if ptr else ""


def _first_of_all_devices(objc, metal):
    """The first device MTLCopyAllDevices reports, or None.

    macOS only -- the call does not exist on iOS, which is why Metal code
    usually reaches for the system default first.
    """
    if not hasattr(metal, "MTLCopyAllDevices"):
        return None
    metal.MTLCopyAllDevices.restype = ctypes.c_void_p
    array = metal.MTLCopyAllDevices()
    if not array:
        return None
    count_fn = ctypes.cast(objc.objc_msgSend,
                           ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p,
                                            ctypes.c_void_p))
    if count_fn(array, objc.sel_registerName(b"count")) < 1:
        return None
    at_fn = ctypes.cast(objc.objc_msgSend,
                        ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_void_p, ctypes.c_ulong))
    return at_fn(array, objc.sel_registerName(b"objectAtIndex:"), 0)


def enumerate_devices():
    """``(devices, reason)``.  Never raises -- see matchedfilter._vulkan."""
    if sys.platform != "darwin":
        return [], "Metal is only available on macOS"
    try:
        metal = ctypes.CDLL(_METAL)
        objc = ctypes.CDLL(_OBJC)
    except OSError as exc:
        return [], "could not load Metal (%s)" % exc

    metal.MTLCreateSystemDefaultDevice.restype = ctypes.c_void_p
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    objc.objc_msgSend.restype = ctypes.c_void_p
    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

    handle = metal.MTLCreateSystemDefaultDevice()
    if not handle:
        # MTLCreateSystemDefaultDevice resolves the DISPLAY device, so it
        # returns nil wherever there is no window-server session -- over
        # ssh, under launchd, and on some CI. That is not the same as having
        # no GPU, and MTLCopyAllDevices answers the question that was
        # actually asked.
        handle = _first_of_all_devices(objc, metal)
    if not handle:
        return [], ("no Metal device: MTLCreateSystemDefaultDevice returned "
                    "nothing and MTLCopyAllDevices is empty. On a virtual "
                    "machine the guest may simply not be given a GPU")

    name = _nsstring(objc, handle, b"name") or "Apple GPU"

    # Two limits decide whether the shipped kernels can run at all, so they
    # are read here rather than discovered at pipeline creation.
    def _uint(selector):
        objc.objc_msgSend.restype = ctypes.c_ulong
        try:
            return int(objc.objc_msgSend(handle, objc.sel_registerName(selector)))
        finally:
            objc.objc_msgSend.restype = ctypes.c_void_p

    try:
        shared = _uint(b"maxThreadgroupMemoryLength")
    except Exception:
        shared = 0
    try:
        low_power = bool(_uint(b"isLowPower"))
    except Exception:
        low_power = False

    return [dict(name=name, vendor=0x106B, kind="integrated",
                 shared_memory=shared, low_power=low_power)], None


def available():
    """``(ok, reason)``.  True only when a Metal device actually exists."""
    devices, reason = enumerate_devices()
    return (True, None) if devices else (False, reason)
