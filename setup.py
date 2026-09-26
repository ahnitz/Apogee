"""Build hook for the matchedfilter extension.

Project metadata lives in pyproject.toml; this file exists only because the
build needs a few compiler flags and Highway's support sources, which
declarative config cannot express.

There are no per-ISA compilation groups any more.  src/kernel.cc includes
hwy/foreach_target.h, so the compiler emits one copy of the kernel per SIMD
target Highway supports on the build machine, each with its own target
attributes, and picks between them at run time.  Nothing below names a target.
"""
import os
import platform
import re
import sys
import sysconfig

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext

BASE = ["-O3", "-fno-math-errno"]
CXX = BASE + ["-std=c++17"]

# Which architectures this compiler invocation is targeting.  On macOS that
# need not be the host: a universal2 build carries "-arch arm64 -arch x86_64"
# and compiles every source twice, so a flag valid for one slice must be valid
# for the other.
_X86 = ("x86_64", "amd64", "i386", "i686")


def target_arches():
    flags = os.environ.get("ARCHFLAGS", "")
    if not flags and sys.platform == "darwin":
        flags = sysconfig.get_config_var("CFLAGS") or ""
    found = re.findall(r"-arch\s+(\S+)", flags)
    return [a.lower() for a in found] or [platform.machine().lower()]


X86_ONLY = all(a in _X86 for a in target_arches())

# Targets Highway must not generate:
#   SVE and RVV have sizeless vectors, which cannot be members of the
#     vf TR[AP_W] arrays the transpose and both stages are built from;
#   SCALAR is one lane, below the four the kernel's layout assumes;
#   the AVX-512 variants beyond AVX3 are code paths nothing has measured a
#     reason for.
DISABLED = ["HWY_SCALAR", "HWY_SVE", "HWY_SVE2", "HWY_SVE_256", "HWY_SVE2_128",
            "HWY_RVV", "HWY_AVX3_DL", "HWY_AVX3_ZEN4", "HWY_AVX3_SPR",
            "HWY_AVX10_2"]

# SSE4.2 as the floor on x86 rather than SSE2: every wider target is reached
# by runtime dispatch, so this restricts nothing beyond hardware from 2008,
# and it removes two more copies of the kernel from the build.  Only when the
# build is x86 alone -- a universal2 arm64 slice cannot be given -msse4.2, so
# there SSE2 has to stay enabled to remain a valid baseline.
if X86_ONLY and platform.machine().lower() in _X86:
    ARCH = ["-msse4.2", "-maes", "-mpclmul"]
    DISABLED += ["HWY_SSE2", "HWY_SSSE3"]
else:
    ARCH = []

HIGHWAY_ROOT = os.environ.get("HIGHWAY_ROOT", "")


HERE = os.path.dirname(os.path.abspath(__file__))


def highway():
    """(include dir, support sources, libraries to link) for Highway.

    The vendored submodule first, so a clone builds without anything
    installed; then HIGHWAY_ROOT, then the usual system places.
    """
    roots = [os.path.join(HERE, "third_party", "highway")]
    if HIGHWAY_ROOT:
        roots.insert(0, HIGHWAY_ROOT)
    roots += ["/usr/include", "/usr/local/include", sys.prefix + "/include"]
    for d in roots:
        if not os.path.isfile(os.path.join(d, "hwy", "highway.h")):
            continue
        # Runtime dispatch needs Highway's CPU detection, which is the one
        # part that is not header-only.  Build it from a source checkout when
        # there is one, and otherwise link the installed library.
        srcs = [os.path.join(d, "hwy", f)
                for f in ("targets.cc", "abort.cc", "per_target.cc")]
        if all(os.path.isfile(s) for s in srcs):
            return d, srcs, []
        return d, [], ["hwy"]
    sys.exit(
        "matchedfilter needs Google Highway to build, and the vendored copy\n"
        "is missing.  From a git clone:\n"
        "    git submodule update --init third_party/highway\n"
        "or install Highway and set HIGHWAY_ROOT to its include directory."
    )


HWY_INC, HWY_SRC, HWY_LIBS = highway()

DEFS = [("HWY_DISABLED_TARGETS", "(%s)" % "|".join(DISABLED))]
# Ablation builds. AP_NOXPOSE=1 removes stage A's corner turn, which makes
# the results WRONG and the timing informative -- it sizes the prize before
# anything is built to win it. It has to be compile-time: as a plan-field
# branch in that loop it measured itself. See balanced-inl.h.
if os.environ.get("AP_NOXPOSE"):
    DEFS = DEFS + [("AP_NOXPOSE", os.environ["AP_NOXPOSE"])]
SOURCES = (
    [("src/kernel.cc", CXX + ARCH, DEFS)]
    + [(s, CXX + ARCH, DEFS) for s in HWY_SRC]   # same baseline, or the
                                                 # dispatch tables disagree
    + [(s, BASE, []) for s in ("src/matchfilt.c", "src/hmf.c", "src/dispatch.c",
                               "python/matchedfilter/_core.c")]
)


class BuildExt(build_ext):
    def build_extension(self, ext):
        objects = []
        os.makedirs(self.build_temp, exist_ok=True)
        for i, (src, flags, defines) in enumerate(SOURCES):
            objects += self.compiler.compile(
                [src],
                output_dir=os.path.join(self.build_temp, "g%d" % i),
                macros=defines,
                include_dirs=ext.include_dirs,
                extra_postargs=flags,
                debug=self.debug,
            )
        self.compiler.link_shared_object(
            objects,
            self.get_ext_fullpath(ext.name),
            libraries=["m"] + HWY_LIBS,
            debug=self.debug,
            target_lang="c++",     # kernel.cc and Highway's own sources
        )


setup(
    ext_modules=[Extension(
        "matchedfilter._core", sources=[],
        include_dirs=["python/matchedfilter", "src", HWY_INC])],
    cmdclass={"build_ext": BuildExt},
    # The tuning tables ship with the library and are read at run time.
    # accuracy.txt describes the algorithm and travels; cost.txt is this
    # machine's timings and is the one a user regenerates. Both are plain
    # text so a wheel can be inspected and a local table diffed against it.
    # Package data lives in pyproject.toml -- a pyproject build ignores a
    # package_data= given here, silently, which is how the SPIR-V came to be
    # absent from a wheel that built and installed without complaint.
)
