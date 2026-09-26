"""Test-session setup.

The only thing here is an import-order workaround, and it needs the
explanation more than the code does.

slangpy must be imported before numpy. Importing numpy first makes Vulkan
device creation fail with "No adapters found" -- a symbol clash between
numpy's bundled libraries and the LLVM that Mesa uses to compile shaders.
pytest imports every test module during collection, most of which import
numpy, so by the time tests/test_gpu.py asks for a device it is far too
late: the GPU tests skip on a machine that has a perfectly good GPU, and
report "no Vulkan device", which looks like a missing driver rather than a
self-inflicted wound.

Doing it here means it happens before any test module is imported.

This is spike-only. The shipped backend will dlopen Vulkan itself with no
C++ runtime of its own, and a direct ctypes probe behaves identically with
and without numpy loaded -- so the clash is slangpy's bundled runtime
against numpy's, not Vulkan against numpy.
"""
try:
    import slangpy            # noqa: F401  -- before numpy, deliberately
except Exception:
    pass                      # absent is fine; the GPU tests will say so


# --- a size this device cannot run is not a failure ------------------------
import pytest                                          # noqa: E402


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Turn UnsupportedSize into a skip, and nothing else.

    n=16384 needs a 1024-thread threadgroup. The Apple Paravirtual device
    allows this kernel 576, so that length is out of reach there -- a fact
    about the hardware, not a fault, and one no amount of fixing will
    change. Every other size runs and agrees with the CPU.

    The narrow exception type is the point. Catching the backend's general
    error here would also swallow a kernel that failed to compile, which is
    exactly the failure these tests exist to catch.
    """
    outcome = yield
    report = outcome.get_result()
    if call.excinfo is None:
        return
    from matchedfilter import UnsupportedSize
    if call.excinfo.errisinstance(UnsupportedSize):
        if (item.config.getoption('--require-coarse-gpu') and
                item.path.name == 'test_coarse_fdr.py'):
            return  # this CI job promises the complete coarse test matrix
        report.outcome = "skipped"
        report.longrepr = (__file__, 0, "unsupported on this device: %s"
                           % call.excinfo.value)
        # Do NOT set report.wasxfail, even to None: pytest tests for the
        # attribute's presence, so assigning it reports an xfail instead of
        # a skip -- which reads as "expected to be broken" rather than
        # "this device cannot do it".


# --- a GPU that enumerates is not a GPU that works -------------------------
_USABLE = "unset"


def usable_gpu():
    """A GPU device string this machine can actually RUN, or None.

    Enumeration is not availability. A Mesa driver that cannot allocate its
    shared memory -- "Failed to create anonymous file for memory
    allocations" -- still enumerates the adapter, so mf.devices() lists a
    GPU and then every attempt to open it raises "no gpu with index 0". On
    such a machine, gating the GPU tests on enumeration alone produced
    dozens of failures that read like defects in this library and were
    nothing of the sort.

    So the probe filters. Opening a context is not enough either, because
    the allocation that fails is the one the first dispatch needs; the
    cheapest honest question is whether a 1024-point filter returns an
    answer. Asked once per session and cached.
    """
    global _USABLE
    if _USABLE != "unset":
        return _USABLE
    _USABLE = None
    try:
        import numpy as np
        import matchedfilter as mf
    except Exception:
        return _USABLE
    for d in mf.devices():
        if d.kind != "gpu" or d.is_software:
            continue
        try:
            f = mf.MatchedFilter(1024, 1, 1, device=str(d))
            z = np.zeros((1, 1024), dtype=np.complex64)
            z[0, 0] = 1.0
            f.set_data(z)
            f.set_templates(z)
            f.run(binsize=1024, threshold=0.0)
        except Exception:
            continue
        _USABLE = str(d)
        break
    return _USABLE


def usable_gpu_reason():
    """Why there is no usable GPU, phrased so it does not mislead."""
    try:
        from matchedfilter import _vulkan
        ok, why = _vulkan.available()
    except Exception as e:                      # pragma: no cover
        return "could not ask for a GPU: %s" % e
    if ok:
        return ("a GPU enumerates but cannot run a filter on this machine "
                "(driver or environment, not the transform length)")
    return why or "no usable GPU"


_VK = "unset"


def vulkan_runs():
    """``(ok, reason)`` -- can a Vulkan CONTEXT actually be opened here?

    _vulkan.available() answers a different question: whether a non-software
    adapter enumerates. That is necessary and not sufficient. A driver that
    cannot allocate its shared memory enumerates fine and raises on context
    creation, so gates built on availability alone let the test body run and
    then report a driver fault as a failure of this library.

    Cached: opening a context is not free, and several modules ask.
    """
    global _VK
    if _VK != "unset":
        return _VK
    try:
        from matchedfilter import _vulkan
        ok, why = _vulkan.available()
    except Exception as e:                      # pragma: no cover
        _VK = (False, "could not ask for Vulkan: %s" % e)
        return _VK
    if not ok:
        _VK = (False, why or "no Vulkan device")
        return _VK
    try:
        from matchedfilter import _vkcompute
        c = _vkcompute.Context(0)
        c.destroy()
    except Exception as e:
        _VK = (False, "a Vulkan device enumerates but will not open here: %s"
                      % str(e).strip().splitlines()[0][:120])
        return _VK
    _VK = (True, None)
    return _VK


def pytest_addoption(parser):
    parser.addoption('--require-coarse-gpu', action='store_true', default=False,
                     help='Fail rather than skip missing coarse-calibration GPU coverage')
