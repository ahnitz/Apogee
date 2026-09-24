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
        report.outcome = "skipped"
        report.longrepr = (__file__, 0, "unsupported on this device: %s"
                           % call.excinfo.value)
        # Do NOT set report.wasxfail, even to None: pytest tests for the
        # attribute's presence, so assigning it reports an xfail instead of
        # a skip -- which reads as "expected to be broken" rather than
        # "this device cannot do it".
