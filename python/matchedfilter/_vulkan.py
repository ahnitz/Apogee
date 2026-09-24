"""Enumerate Vulkan devices through the system loader, with ctypes.

Deliberately not slangpy.  slangpy is how the kernels are *compiled*, which
happens at build time; making it a runtime import would put a heavyweight
dependency -- and its numpy import-order clash -- in front of every user who
merely wants to ask what hardware exists.  Enumeration needs four entry points,
so it is cheaper to call them directly than to inherit a framework.

Nothing here forces ``VK_ICD_FILENAMES``.  An earlier version probed ICDs by
name and concluded from the failures that probing "poisons the loader"; that
was wrong, and setting the variable was itself causing ``vkCreateInstance`` to
fail with ``VK_ERROR_INCOMPATIBLE_DRIVER``.  The loader's own discovery works.
See ``_shadowing_hint`` for what the failures actually were.
"""
import ctypes
import os

_VK_SUCCESS = 0

# VkPhysicalDeviceType.  Reported as-is rather than collapsed to gpu/not-gpu,
# because the distinction matters to the caller: "cpu" is a software
# rasteriser (lavapipe), which is correct but roughly three orders of
# magnitude slower, and must never be picked by an unqualified device="gpu".
_TYPES = {0: "other", 1: "integrated", 2: "discrete", 3: "virtual", 4: "cpu"}


class _AppInfo(ctypes.Structure):
    _fields_ = [("sType", ctypes.c_uint32), ("pNext", ctypes.c_void_p),
                ("pApplicationName", ctypes.c_char_p),
                ("applicationVersion", ctypes.c_uint32),
                ("pEngineName", ctypes.c_char_p),
                ("engineVersion", ctypes.c_uint32),
                ("apiVersion", ctypes.c_uint32)]


class _InstInfo(ctypes.Structure):
    _fields_ = [("sType", ctypes.c_uint32), ("pNext", ctypes.c_void_p),
                ("flags", ctypes.c_uint32),
                ("pApplicationInfo", ctypes.POINTER(_AppInfo)),
                ("enabledLayerCount", ctypes.c_uint32),
                ("ppEnabledLayerNames", ctypes.c_void_p),
                ("enabledExtensionCount", ctypes.c_uint32),
                ("ppEnabledExtensionNames", ctypes.c_void_p)]


def _shadowing_hint():
    """Why a healthy machine can report no Vulkan devices at all.

    Mesa's ICDs link against the system libstdc++.  A conda or similar prefix
    early on the search path supplies an older one -- miniconda ships 6.0.29,
    which lacks the GLIBCXX_3.4.30 and 3.4.32 symbols the drivers need -- and
    then *every* ICD fails to load and the loader reports, accurately but
    unhelpfully, that it found no valid GPUs.

    This is worth a sentence of its own because the observable symptom is
    indistinguishable from having no GPU, and conda is common enough that
    guessing wrong here costs a user an afternoon.
    """
    try:
        with open("/proc/self/maps") as fh:
            for line in fh:
                if "libstdc++" in line:
                    path = line.split()[-1]
                    if "conda" in path or not path.startswith(("/usr/lib", "/lib")):
                        return (" -- note that %s is shadowing the system "
                                "libstdc++, which stops Mesa drivers loading; "
                                "try LD_PRELOAD=/usr/lib64/libstdc++.so.6"
                                % path)
                    break
    except OSError:
        pass
    return ""


def _platform_note():
    """Why a platform might have no Vulkan at all, as opposed to no GPU.

    "no GPU" is the wrong thing to tell a Mac user. There is a GPU; this
    library has no way to reach it, which is a different statement and the
    only one that tells them what to do about it.
    """
    import sys
    if sys.platform == "darwin":
        return (" -- macOS ships no Vulkan driver. An Apple GPU is reached "
                "through the Metal backend instead, which device='gpu' "
                "selects on its own; only code asking for Vulkan by name "
                "lands here (see docs/gpu-notes.md)")
    return ""


def _load():
    for name in ("libvulkan.so.1", "libvulkan.1.dylib", "vulkan-1.dll"):
        try:
            return ctypes.CDLL(name), None
        except OSError:
            continue
    return None, ("no Vulkan loader (libvulkan) found on this system"
                  + _platform_note())


def enumerate_devices():
    """``(devices, reason)``; devices is a list of dicts, reason explains empty.

    Never raises.  Asking what hardware exists is something a user does to find
    out whether anything is wrong, so it must not itself be a thing that can go
    wrong.
    """
    vk, err = _load()
    if vk is None:
        return [], err

    vk.vkCreateInstance.argtypes = [ctypes.POINTER(_InstInfo), ctypes.c_void_p,
                                    ctypes.POINTER(ctypes.c_void_p)]
    vk.vkEnumeratePhysicalDevices.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_void_p)]

    # Vulkan 1.1: the floor for subgroup queries, and old enough that every
    # driver we would want to run on supports it.
    app = _AppInfo(0, None, b"matchedfilter", 1, b"matchedfilter", 1,
                   (1 << 22) | (1 << 12))
    ci = _InstInfo(1, None, 0, ctypes.pointer(app), 0, None, 0, None)
    inst = ctypes.c_void_p()
    if vk.vkCreateInstance(ctypes.byref(ci), None, ctypes.byref(inst)) != _VK_SUCCESS:
        return [], "vkCreateInstance failed" + _shadowing_hint()

    try:
        count = ctypes.c_uint32(0)
        rc = vk.vkEnumeratePhysicalDevices(inst, ctypes.byref(count), None)
        if rc != _VK_SUCCESS or count.value == 0:
            return [], ("the Vulkan loader found no usable devices"
                        + _shadowing_hint())
        handles = (ctypes.c_void_p * count.value)()
        if vk.vkEnumeratePhysicalDevices(inst, ctypes.byref(count),
                                         handles) != _VK_SUCCESS:
            return [], "vkEnumeratePhysicalDevices failed"

        out = []
        buf = (ctypes.c_ubyte * 2048)()   # VkPhysicalDeviceProperties is ~880
        for handle in handles:
            vk.vkGetPhysicalDeviceProperties(ctypes.c_void_p(handle),
                                             ctypes.byref(buf))
            words = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint32))
            # layout: apiVersion, driverVersion, vendorID, deviceID,
            # deviceType, then deviceName[256]
            out.append(dict(name=bytes(buf[20:20 + 256]).split(b"\0")[0].decode(
                                "utf-8", "replace"),
                            vendor=int(words[2]),
                            device_id=int(words[3]),
                            kind=_TYPES.get(int(words[4]), "other")))
        return out, None
    finally:
        vk.vkDestroyInstance(inst, None)


def available():
    """``(ok, reason)`` -- is there a Vulkan device worth dispatching to?

    A software rasteriser does not count.  It is invaluable for testing the
    kernels without a GPU runner, but returning it here would let an
    unqualified ``device="gpu"`` silently land on something far slower than
    the CPU backend it bypassed.
    """
    devices, reason = enumerate_devices()
    real = [d for d in devices if d["kind"] != "cpu"]
    if real:
        return True, None
    if devices:
        return False, ("only software Vulkan devices found (%s)"
                       % ", ".join(d["name"] for d in devices))
    return False, reason
