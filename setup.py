"""Builds the peakfft extension.

AVX-512 is requested explicitly rather than via -march=native so the wheel does
not silently inherit whatever the build host happens to be.  The library needs
AVX-512 F/DQ/BW/VL; there is no fallback path.
"""
from setuptools import setup, Extension

FLAGS = ["-O3", "-mavx512f", "-mavx512dq", "-mavx512bw", "-mavx512vl",
         "-fno-math-errno", "-std=gnu11"]

setup(
    ext_modules=[
        Extension(
            "peakfft._core",
            sources=[
                "python/peakfft/_core.c",
                "src/kernel1024.c",
                "src/fft_small.c",
                "src/fft1m.c",
                "src/plan.c",
            ],
            include_dirs=["include", "src"],
            extra_compile_args=FLAGS,
        )
    ],
)
