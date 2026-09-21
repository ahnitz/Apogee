"""Build hook for the matchedfilter extension.

Project metadata lives in pyproject.toml; this file exists only because the
build needs per-source compiler flags, which declarative config cannot express.

The AVX-512 sources, the AVX2 sources and the dispatcher must be compiled with
different -m flags so the module can be *loaded* on a machine without AVX-512
and still select a working back end at runtime.  setuptools has no notion of
per-file flags, so the groups are compiled here and linked together.
"""
import os
import platform
import re
import sys
import sysconfig

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext

# x86 gets the hand-written AVX-512 and AVX2 kernels; everywhere else builds
# only the portable back end, which is the same source compiled against
# compiler vector extensions.  Selecting sources by architecture rather than
# refusing to build is what lets this run on arm64 and macOS.
#
# The decision is about the TARGET architectures, which on macOS need not be
# the host: Python there is commonly configured to build universal2, so one
# compiler invocation carries -arch arm64 -arch x86_64 and every source is
# compiled twice.  A mixed target cannot use x86-only kernels, because the
# arm64 slice would have to compile them too.
_X86 = ("x86_64", "amd64", "i386", "i686")


def target_arches():
    flags = os.environ.get("ARCHFLAGS", "")
    if not flags and sys.platform == "darwin":
        flags = sysconfig.get_config_var("CFLAGS") or ""
    found = re.findall(r"-arch\s+(\S+)", flags)
    return [a.lower() for a in found] or [platform.machine().lower()]


ARCHES = target_arches()
IS_X86 = all(a in _X86 for a in ARCHES)

BASE = ["-O3", "-fno-math-errno"]
CXX = BASE + ["-std=c++17"]

# Highway's AVX2 and AVX-512 targets need more than -mavx2/-mavx512f; without
# the rest its baseline detection silently falls back to SSE4 and FixedTag
# hands back 4 lanes where 8 or 16 were asked for.
HWY_AVX2 = CXX + ["-mavx2", "-mfma", "-mbmi", "-mbmi2", "-mf16c", "-mlzcnt"]
HWY_AVX3 = HWY_AVX2 + ["-mavx512f", "-mavx512dq", "-mavx512bw", "-mavx512vl"]
HWY_BASE = CXX + (["-msse4.2"] if platform.machine().lower()
                  in ("x86_64", "amd64") else [])

HIGHWAY_ROOT = os.environ.get("HIGHWAY_ROOT", "")


def highway_include():
    """Where Highway's headers are, or None."""
    if HIGHWAY_ROOT and os.path.isfile(
            os.path.join(HIGHWAY_ROOT, "hwy", "highway.h")):
        return HIGHWAY_ROOT
    for d in ("/usr/include", "/usr/local/include"):
        if os.path.isfile(os.path.join(d, "hwy", "highway.h")):
            return d
    return None


HWY_INC = highway_include()
if HWY_INC is None:
    sys.exit(
        "matchedfilter needs Google Highway headers to build.\n"
        "Install them, or set HIGHWAY_ROOT to a checkout of\n"
        "https://github.com/google/highway"
    )

IS_X86 = platform.machine().lower() in ("x86_64", "amd64", "i386", "i686")

# One kernel, compiled once per lane count.  Highway's FixedTag cannot exceed
# the target's native vector, so width and target flags go together.  Off x86
# only the 4-lane build applies, which is what NEON gives.
GROUPS = [
    ("src/balanced_hwy.cc", HWY_BASE,
     [("AP_W", "4"), ("AP_HIGHWAY", "1"), ("HWY_COMPILE_ONLY_STATIC", "1")]),
]
X86_ONLY = [] if IS_X86 else [("AP_NO_WIDE_KERNELS", "1")]
if IS_X86:
    GROUPS += [
        ("src/balanced_hwy.cc", HWY_AVX2,
         [("AP_W", "8"), ("AP_HIGHWAY", "1"), ("HWY_COMPILE_ONLY_STATIC", "1"),
          ("HWY_BASELINE_TARGETS", "HWY_AVX2")]),
        ("src/balanced_hwy.cc", HWY_AVX3,
         [("AP_W", "16"), ("AP_HIGHWAY", "1"), ("HWY_COMPILE_ONLY_STATIC", "1"),
          ("HWY_BASELINE_TARGETS", "HWY_AVX3")]),
    ]
GROUPS += [
    ("src/matchfilt.c",  BASE, []),
    ("src/hmf.c",        BASE, []),
    ("src/dispatch.c",   [],   X86_ONLY),      # baseline only: runs first
    ("python/matchedfilter/_core.c", [], []),
]

class BuildExt(build_ext):
    def build_extension(self, ext):
        objects = []
        tmp = self.build_temp
        os.makedirs(tmp, exist_ok=True)
        for i, (src, flags, defines) in enumerate(GROUPS):
            outdir = os.path.join(tmp, "g%d" % i)
            objs = self.compiler.compile(
                [src],
                output_dir=outdir,
                macros=defines,
                include_dirs=ext.include_dirs,
                extra_postargs=BASE + flags,
                debug=self.debug,
            )
            objects.extend(objs)
        self.compiler.link_shared_object(
            objects,
            self.get_ext_fullpath(ext.name),
            libraries=["m"],
            debug=self.debug,
        )


setup(
    ext_modules=[Extension(
        "matchedfilter._core", sources=[],
        include_dirs=["python/matchedfilter", "src", HWY_INC])],
    cmdclass={"build_ext": BuildExt},
)
