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
import sys

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext

# The kernels are x86 SIMD intrinsics.  There is no portable fallback, so fail
# here with something a reader can act on rather than 200 lines of "unknown
# type name '__m512'" from the compiler.  pip only reaches this if it fell back
# to the sdist, which means no wheel matched the platform.
_MACHINE = platform.machine().lower()
if _MACHINE not in ("x86_64", "amd64"):
    sys.exit(
        "matchedfilter only builds on x86-64 (found %r).\n"
        "The kernels are AVX2/AVX-512 intrinsics with no portable fallback.\n"
        "Support for other architectures is not implemented." % platform.machine()
    )

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

# (source, extra flags, extra defines)
GROUPS = [
    ("src/kernel1024.c", AVX512, []),
    ("src/be_avx512.c",  AVX512, []),
    ("src/balanced.c",   AVX512, []),                   # generic source, 16 lanes
    ("src/balanced.c",   AVX2,   [("AP_W", "8")]),      # generic source, 8 lanes
    # Same source a third time, compiler-vectorised.  Built on x86 too so the
    # two can be compared in one process; on other architectures it is the
    # only back end there is.
    ("src/balanced.c",   AVX2,   [("AP_W", "8"), ("AP_PORTABLE", "1")]),  # tuned below
    ("src/matchfilt.c",  BASE,   []),
    ("src/hmf.c",        BASE,   []),
    ("src/dispatch.c",   [],     []),                 # baseline only
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
