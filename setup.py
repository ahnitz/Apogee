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

BASE = ["-O3", "-fno-math-errno", "-std=gnu11"]

# The portable back end is already explicitly vectorised, and GCC's SLP pass
# tries to vectorise it again: it re-splits and recombines vectors that were
# fine, and the result runs 2.3x slower than the AVX2 intrinsics at -O3 while
# executing the same number of instructions.  Disabling that one pass takes
# the transform from 2.30x to 1.02x.  -O2 also avoids it, at the cost of
# everything else -O3 does.
#
# Clang does not show the same regression, so the flags are GCC-only and are
# probed rather than assumed -- an unknown flag is a hard error on some
# toolchains, and silently dropping it would put the 2.3x back.
PORTABLE_TUNING = ["-fno-tree-slp-vectorize", "-fno-unswitch-loops"]


def _accepted(compiler, flags):
    """Keep only flags this compiler actually accepts."""
    import tempfile
    ok = []
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "probe.c")
        with open(src, "w") as fh:
            fh.write("int main(void){return 0;}\n")
        for f in flags:
            try:
                compiler.compile([src], output_dir=d, extra_postargs=[f, "-Werror"])
                ok.append(f)
            except Exception:
                pass
    return ok
AVX512 = ["-DAP_W=16", "-mavx512f", "-mavx512dq", "-mavx512bw", "-mavx512vl"]
AVX2 = ["-mavx2", "-mfma"]

# Compiled into every slice, so an arm64 slice of a universal2 build never
# references kernels that were not built.
X86_KERNELS = ("AP_WITH_X86_KERNELS", "1" if IS_X86 else "0")

# (source, extra flags, extra defines)
if IS_X86:
    GROUPS = [
        ("src/kernel1024.c", AVX512, []),
        ("src/be_avx512.c",  AVX512, []),
        ("src/balanced.c",   AVX512, []),                   # generic source, 16 lanes
        ("src/balanced.c",   AVX2,   [("AP_W", "8")]),      # generic source, 8 lanes
        # Same source a third time, compiler-vectorised.  Built on x86 too so
        # the two can be compared inside one process.
        ("src/balanced.c",   AVX2,   [("AP_W", "8"), ("AP_PORTABLE", "1")]),
        ("src/matchfilt.c",  BASE,   [X86_KERNELS]),
        ("src/hmf.c",        BASE,   []),
        ("src/dispatch.c",   [],     [X86_KERNELS]),      # baseline only
        ("python/matchedfilter/_core.c", [], []),
    ]
else:
    # No -m flags: the vector extensions lower to whatever the target has
    # (NEON on arm64), and naming an ISA here would only restrict it.
    GROUPS = [
        ("src/balanced.c",   [], [("AP_W", "8"), ("AP_PORTABLE", "1")]),
        ("src/matchfilt.c",  BASE, [X86_KERNELS]),
        ("src/hmf.c",        BASE, []),
        ("src/dispatch.c",   [],   [X86_KERNELS]),
        ("python/matchedfilter/_core.c", [], []),
    ]


class BuildExt(build_ext):
    def build_extension(self, ext):
        objects = []
        tmp = self.build_temp
        os.makedirs(tmp, exist_ok=True)
        tuning = _accepted(self.compiler, PORTABLE_TUNING)
        for i, (src, flags, defines) in enumerate(GROUPS):
            if ("AP_PORTABLE", "1") in defines:
                flags = flags + tuning
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
    ext_modules=[Extension("matchedfilter._core", sources=[], include_dirs=["python/matchedfilter", "src"])],
    cmdclass={"build_ext": BuildExt},
)
