"""The Metal kernels: generated, complete, and lowering to native primitives.

These run everywhere, including on Linux with no Apple hardware, because
what they check is the BUILD OUTPUT rather than execution. That is the part
that can silently rot: Slang marks its Metal target work in progress, so a
release that starts emulating a wave reduction instead of emitting simd_max
would still compile, still be correct, and quietly cost most of the
performance.

Running the kernels needs a Mac and is covered by the macOS CI job.
"""
import json
import pathlib

import pytest

import matchedfilter

METAL_DIR = pathlib.Path(matchedfilter.__file__).resolve().parent / "metal"
MANIFEST = (pathlib.Path(matchedfilter.__file__).resolve().parent
            / "spirv" / "manifest.json")

pytestmark = pytest.mark.skipif(not METAL_DIR.is_dir(),
                                reason="Metal kernels not built into this tree")


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_text())


def test_every_size_has_metal(manifest):
    """A macOS wheel must carry the same coverage as a Linux one."""
    for key, info in manifest["modules"].items():
        assert "metal" in info, "n=%s has no Metal output" % key
        for entry, files in info["metal"].items():
            src = METAL_DIR / files["msl"]
            assert src.is_file(), "%s missing" % src
            assert src.stat().st_size > 1000, "%s looks empty" % src


@pytest.mark.parametrize("n", [1024, 4096, 16384])
def test_the_wave_reduction_is_native(manifest, n):
    """simd_max, not a shared-memory loop pretending to be one.

    This is the single thing that decided Metal over a translation layer,
    and it is a property of Slang's code generator rather than of this
    source -- so it is worth asserting rather than assuming it stays true
    across upgrades.
    """
    src = (METAL_DIR / manifest["modules"][str(n)]["metal"]["gatedTierB"]["msl"]).read_text()
    assert "simd_max" in src, "the wave reduction stopped lowering to simd_max"
    assert "simd_is_first" in src


@pytest.mark.parametrize("n", [1024, 4096, 16384])
def test_shared_memory_and_atomics_are_native(manifest, n):
    src = (METAL_DIR / manifest["modules"][str(n)]["metal"]["fusedTierB"]["msl"]).read_text()
    assert "threadgroup" in src, "no threadgroup storage"
    assert "threadgroup_barrier" in src
    assert "atomic_fetch_max_explicit" in src, \
        "the per-bin maximum stopped using a native atomic"


def test_the_coarse_kernel_has_metal():
    assert (METAL_DIR / "coarse_256.metal").is_file()


def test_metallib_presence_is_recorded(manifest):
    """Whether a compiled library shipped is a fact about the BUILD.

    It is built only where Apple's compiler exists, so on a Linux build it
    is absent and the manifest says so. What must not happen is the
    manifest claiming one that is not there -- the runtime would then load
    nothing and fail on the user's machine.
    """
    for info in manifest["modules"].values():
        for files in info["metal"].values():
            lib = files.get("metallib")
            if lib is not None:
                assert (METAL_DIR / lib).is_file(), \
                    "manifest claims %s but it is not in the package" % lib
