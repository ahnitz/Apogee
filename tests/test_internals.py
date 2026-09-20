"""Build and run the one remaining C test.

Everything else is exercised through the Python API.  This one cannot be:
tests/test_units.c checks the register transpose, the generated codelets and
the int16 path directly against a double-precision DFT, and none of those are
reachable from outside the library.

It compiles from source, so it only runs in a repository checkout -- an
installed wheel has no src/ to build against, and the test skips.
"""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")

# AVX-512 sources, AVX2 sources and the dispatcher need different -m flags:
# compiling the lot with -mavx512f would produce a binary that crashes on a
# machine without it, which is the situation the dispatcher exists to avoid.
UNITS = [
    ("kernel1024.c", ["-DAP_W=16", "-mavx512f", "-mavx512dq", "-mavx512bw", "-mavx512vl"]),
    ("be_avx512.c",  ["-DAP_W=16", "-mavx512f", "-mavx512dq", "-mavx512bw", "-mavx512vl"]),
    ("balanced.c",   ["-DAP_W=16", "-mavx512f", "-mavx512dq", "-mavx512bw", "-mavx512vl"]),
    ("balanced.c",   ["-DAP_W=8", "-mavx2", "-mfma"]),
    ("dispatch.c",   []),
    ("matchfilt.c",  []),
    ("hmf.c",        []),
]


def _have_avx512():
    try:
        with open("/proc/cpuinfo") as fh:
            return "avx512vl" in fh.read()
    except OSError:
        return False


@pytest.mark.skipif(not os.path.isdir(SRC), reason="not a source checkout")
@pytest.mark.skipif(shutil.which("cc") is None, reason="no C compiler")
@pytest.mark.skipif(sys.platform != "linux", reason="x86 Linux only")
@pytest.mark.skipif(not _have_avx512(), reason="test_units.c is AVX-512 only")
def test_c_internals(tmp_path):
    common = ["-O2", "-I", SRC, "-I", os.path.join(ROOT, "python", "apogee")]
    objs = []
    for i, (name, flags) in enumerate(UNITS):
        obj = str(tmp_path / ("u%d.o" % i))
        subprocess.run(["cc", "-c", os.path.join(SRC, name), "-o", obj]
                       + common + flags, check=True)
        objs.append(obj)

    exe = str(tmp_path / "test_units")
    subprocess.run(["cc", os.path.join(ROOT, "tests", "test_units.c"), "-o", exe]
                   + common
                   + ["-DAP_W=16", "-mavx512f", "-mavx512dq", "-mavx512bw", "-mavx512vl",
                      "-I", os.path.join(ROOT, "tests")]
                   + objs + ["-lm"], check=True)

    done = subprocess.run([exe], capture_output=True, text=True)
    # The C harness prints one line per check and exits non-zero on failure;
    # surface its output so a CI failure says which check broke.
    assert done.returncode == 0, done.stdout + done.stderr
