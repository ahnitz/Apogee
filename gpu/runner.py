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


def _icd_candidates():
    """ICD files to try, in preference order.

    A real GPU first, then lavapipe -- software Vulkan, far too slow to
    benchmark and entirely adequate to prove correctness, which is what
    lets the GPU kernels be tested on a runner with no GPU at all.
    """
    if os.environ.get("VK_ICD_FILENAMES"):
        return [os.environ["VK_ICD_FILENAMES"]]
    d = pathlib.Path("/usr/share/vulkan/icd.d")
    if not d.is_dir():
        return [None]
    # Order matters: trying an ICD for hardware that is not here can leave
    # the loader unable to create an instance at all, so the later
    # candidates fail too. Ask for the likely ones by name, then the
    # software rasteriser, then let the loader decide.
    likely = ("radeon", "amdgpu", "nvidia", "intel")
    out = [str(p) for name in likely for p in sorted(d.glob("%s*_icd.*.json" % name))]
    out += [str(p) for p in sorted(d.glob("lvp_icd.*.json"))]
    return out + [None]


def available():
    """(ok, reason). Never raises."""
    global _SPY
    try:
        import slangpy
        _SPY = slangpy
    except Exception as e:
        return False, "slangpy not installed (%s)" % type(e).__name__
    for icd in _icd_candidates():
        old = os.environ.get("VK_ICD_FILENAMES")
        if icd:
            os.environ["VK_ICD_FILENAMES"] = icd
        try:
            dev = _SPY.Device(type=_SPY.DeviceType.vulkan)
            return True, dev.info.adapter_name
        except Exception:
            pass
        finally:
            if icd:
                if old is None:
                    os.environ.pop("VK_ICD_FILENAMES", None)
                else:
                    os.environ["VK_ICD_FILENAMES"] = old
    return False, "no Vulkan device (tried %d ICDs)" % len(_icd_candidates())


def device():
    ok, why = available()
    if not ok:
        raise RuntimeError(why)
    for icd in _icd_candidates():
        if icd:
            os.environ["VK_ICD_FILENAMES"] = icd
        try:
            return _SPY.Device(type=_SPY.DeviceType.vulkan)
        except Exception:
            continue
    raise RuntimeError(why)


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
