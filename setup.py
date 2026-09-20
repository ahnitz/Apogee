"""Builds the apogee extension with per-source ISA flags.

The AVX-512 sources, the AVX2 sources and the dispatcher must be compiled with
different -m flags so the resulting module can be *loaded* on a machine without
AVX-512 and still pick a working back end at runtime.  setuptools has no notion
of per-file flags, so we compile the groups ourselves and link them together.
"""
import os
from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext

BASE = ["-O3", "-fno-math-errno", "-std=gnu11"]
AVX512 = ["-DAP_W=16", "-mavx512f", "-mavx512dq", "-mavx512bw", "-mavx512vl"]
AVX2 = ["-mavx2", "-mfma"]

# (source, extra flags, extra defines)
GROUPS = [
    ("src/kernel1024.c", AVX512, []),
    ("src/be_avx512.c",  AVX512, []),
    ("src/balanced.c",   AVX512, []),                   # generic source, 16 lanes
    ("src/balanced.c",   AVX2,   [("AP_W", "8")]),      # generic source, 8 lanes
    ("src/matchfilt.c",  BASE,   []),
    ("src/dispatch.c",   [],     []),                 # baseline only
    ("python/apogee/_core.c", [], []),
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
    ext_modules=[Extension("apogee._core", sources=[], include_dirs=["include", "src"])],
    cmdclass={"build_ext": BuildExt},
)
