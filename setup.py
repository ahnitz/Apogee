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
import sys

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext

BASE = ["-O3", "-fno-math-errno"]
CXX = BASE + ["-std=c++17"]

# Targets Highway must not generate:
#   SVE and RVV have sizeless vectors, which cannot be members of the
#     vf TR[AP_W] arrays the transpose and both stages are built from;
#   SCALAR is one lane, below the four the kernel's layout assumes;
#   the AVX-512 variants beyond AVX3, and the pre-SSE4 targets, are code paths
#     nothing has measured a reason for.
DISABLED = "(HWY_SCALAR|HWY_SVE|HWY_SVE2|HWY_SVE_256|HWY_SVE2_128|HWY_RVV" \
           "|HWY_SSE2|HWY_SSSE3|HWY_AVX3_DL|HWY_AVX3_ZEN4|HWY_AVX3_SPR" \
           "|HWY_AVX10_2)"

# SSE4.2 as the floor on x86 rather than SSE2: it is the oldest target left
# enabled, and Highway needs the baseline to be one it will generate.  Every
# wider target is reached by runtime dispatch, so this does not restrict what
# the build can run on beyond hardware from 2008.
if any(s in (os.environ.get("ARCHFLAGS", "") or "") for s in ("arm64", "aarch64")):
    ARCH = []
elif os.uname().machine.lower() in ("x86_64", "amd64", "i386", "i686"):
    ARCH = ["-msse4.2", "-maes", "-mpclmul"]
else:
    ARCH = []

HIGHWAY_ROOT = os.environ.get("HIGHWAY_ROOT", "")


def highway():
    """(include dir, support sources, libraries to link) for Highway."""
    roots = [HIGHWAY_ROOT] if HIGHWAY_ROOT else []
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
        "matchedfilter needs Google Highway to build.\n"
        "Install it, or set HIGHWAY_ROOT to a checkout of\n"
        "https://github.com/google/highway"
    )


HWY_INC, HWY_SRC, HWY_LIBS = highway()

DEFS = [("HWY_DISABLED_TARGETS", DISABLED)]
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
)
