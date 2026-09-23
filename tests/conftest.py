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
