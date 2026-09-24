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


def _all_devices(objc, metal):
    """Every Metal device, via MTLCopyAllDevices.

    This is the RIGHT call for compute, and MTLCreateSystemDefaultDevice is
    not. That one returns the device the system recommends for RENDERING --
    it resolves against the display -- so it is nil on any headless machine:
    over ssh, under launchd, on CI. A compute kernel needs no display, and
    treating a missing one as a missing GPU is a category error the API
    invites.

    It is macOS-only, which is why Metal examples reach for the system
    default first; on iOS there is exactly one device and the question does
    not arise.
    """
    if not hasattr(metal, "MTLCopyAllDevices"):
        return []
    metal.MTLCopyAllDevices.restype = ctypes.c_void_p
    array = metal.MTLCopyAllDevices()
    if not array:
        return []
    count_fn = ctypes.cast(objc.objc_msgSend,
                           ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p,
                                            ctypes.c_void_p))
    count = int(count_fn(array, objc.sel_registerName(b"count")))
    at_fn = ctypes.cast(objc.objc_msgSend,
                        ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_void_p, ctypes.c_ulong))
    sel = objc.sel_registerName(b"objectAtIndex:")
    return [at_fn(array, sel, i) for i in range(count)]


def _first_of_all_devices(objc, metal):
    """Back-compat shim for the runtime; prefer _all_devices."""
    found = _all_devices(objc, metal)
    return found[0] if found else None


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

    # Enumerate first, and fall back to the system default only if the
    # enumeration is unavailable. A display is irrelevant to compute.
    handles = _all_devices(objc, metal)
    if not handles:
        one = metal.MTLCreateSystemDefaultDevice()
        handles = [one] if one else []
    if not handles:
        return [], ("no Metal device: MTLCopyAllDevices is empty and "
                    "MTLCreateSystemDefaultDevice returned nothing either. "
                    "On a virtual machine the guest may simply not be given "
                    "a GPU")

    out = []
    for handle in handles:
        name = _nsstring(objc, handle, b"name") or "Apple GPU"

        # Read the limit that decides whether the shipped kernels can run
        # here rather than discovering it at pipeline creation.
        def _uint(selector, dev=handle):
            fn = ctypes.cast(objc.objc_msgSend,
                             ctypes.CFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p,
                                              ctypes.c_void_p))
            return int(fn(dev, objc.sel_registerName(selector)))

        try:
            shared = _uint(b"maxThreadgroupMemoryLength")
        except Exception:
            shared = 0
        out.append(dict(name=name, vendor=0x106B, kind="integrated",
                        shared_memory=shared))
    return out, None


def available():
    """``(ok, reason)``.  True only when a Metal device actually exists."""
    devices, reason = enumerate_devices()
    return (True, None) if devices else (False, reason)
