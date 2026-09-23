"""Running the GPU kernels, with every reason they might not run named.

This is the spike's runner, not the shipped backend. The shipped one will
dlopen Vulkan and dispatch embedded SPIR-V; this one drives slangpy, which
is the fastest way to iterate and is not a dependency of the package.

Everything here is written so a caller can ask "can this run?" and get a
reason rather than an exception, because the tests have to skip cleanly on
a machine with no GPU, no driver, or no toolchain -- which is most CI.
"""
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent

#: Slang must be imported before numpy. Importing numpy first makes Vulkan
#: device creation fail with "No adapters found" -- a symbol clash between
#: numpy's bundled libraries and the LLVM Mesa uses for shader compilation.
#: Spike-only: the shipped backend dlopens Vulkan itself with no C++
#: runtime of its own.
_SPY = None


def available():
    """(ok, reason). Never raises.

    No ICD is forced.  An earlier version walked /usr/share/vulkan/icd.d
    setting VK_ICD_FILENAMES to each candidate in turn, on the theory that
    probing an ICD for absent hardware poisons the loader for the later
    candidates.  That theory was wrong: setting the variable was itself the
    failure.  With it pointing at the radeon ICD, vkCreateInstance returns
    VK_ERROR_INCOMPATIBLE_DRIVER on a machine whose radeon driver works
    perfectly when the loader is left to its own discovery.

    The failures that motivated the probing were a shadowed libstdc++ --
    see matchedfilter._vulkan._shadowing_hint, which reports it as a cause
    instead of leaving it to be misread as absent hardware.
    """
    global _SPY
    try:
        import slangpy
        _SPY = slangpy
    except Exception as e:
        return False, "slangpy not installed (%s)" % type(e).__name__
    try:
        dev = _SPY.Device(type=_SPY.DeviceType.vulkan)
        return True, dev.info.adapter_name
    except Exception as e:
        import sys
        sys.path.insert(0, str(HERE.parent / "python"))
        try:
            from matchedfilter._vulkan import enumerate_devices
            _, why = enumerate_devices()
        except Exception:
            why = None
        return False, why or "no Vulkan device (%s)" % type(e).__name__


def device():
    ok, why = available()
    if not ok:
        raise RuntimeError(why)
    return _SPY.Device(type=_SPY.DeviceType.vulkan)


def peaks(dev, n, data, tmpl, kernel="tierb.slang", entry="fusedTierB"):
    """Peak magnitude per (data, template) pair, on the device.

    `data` and `tmpl` are complex64 spectra, shaped (nd, n) and (nt, n).
    Returns a float32 array of shape (nd, nt).
    """
    import numpy as np
    src = ("#define NLEN %d\n" % n) + (HERE / kernel).read_text()
    mod = dev.load_module_from_source("mf_%d" % n, src)
    kern = dev.create_compute_kernel(dev.link_program([mod], [mod.entry_point(entry)]))
    nd, nt = data.shape[0], tmpl.shape[0]
    wg = n // 16
    mk = lambda cnt, sz, rw, d=None: dev.create_buffer(
        element_count=cnt, struct_size=sz,
        usage=_SPY.BufferUsage.unordered_access if rw else _SPY.BufferUsage.shader_resource,
        data=d)
    bd = mk(data.size, 8, False, np.ascontiguousarray(data).view(np.float32))
    bh = mk(tmpl.size, 8, False, np.ascontiguousarray(tmpl).view(np.float32))
    bm = mk(nd * nt, 4, True)
    kern.dispatch(thread_count=[nd * nt * wg, 1, 1],
                  data=bd, tmpl=bh, peakMag=bm, ntmpl=nt)
    dev.wait()
    return bm.to_numpy().view(np.float32).reshape(nd, nt)
