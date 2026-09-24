"""The shipped SPIR-V, and whether it still matches the source it came from.

A stale kernel blob is a dangerous failure because it is silent: the module
loads, dispatches, and returns plausible numbers computed by the wrong code.
This project has already paid for that once -- a stale `N = 2048` left in a
kernel made a baseline 2.8x too slow, which would have flattered a speedup by
the same factor, and it was caught only because an unrelated figure was
printed beside it.

So the blobs are checked two ways: their host-side contract is pinned here,
and when slangc is present they are recompiled and compared byte for byte.
"""
import json
import pathlib
import struct

import pytest

import matchedfilter

SPIRV_DIR = pathlib.Path(matchedfilter.__file__).resolve().parent / "spirv"
MANIFEST = SPIRV_DIR / "manifest.json"

def test_the_kernels_are_present_in_the_installed_package():
    """The GPU blobs must travel with the package, and this must FAIL loudly.

    It was a skip once, and that hid a real bug: setup.py carried a
    package_data= listing the SPIR-V, a pyproject build ignores that
    argument, and the wheel shipped without a single kernel in it. The build
    succeeded, the install succeeded, and only device="gpu" would have found
    out -- on the user's machine.
    """
    assert MANIFEST.is_file(), (
        "%s is missing. Run tools/build_spirv.py, and if this is an installed "
        "package check [tool.setuptools.package-data] in pyproject.toml."
        % MANIFEST)
    import json
    for info in json.loads(MANIFEST.read_text())["modules"].values():
        blob = SPIRV_DIR / info["file"]
        assert blob.is_file(), "%s missing from the package" % blob
        assert blob.stat().st_size == info["bytes"]


@pytest.fixture(scope="module")
def manifest():
    return json.loads(MANIFEST.read_text())


def test_every_tier_b_size_is_present(manifest):
    import sys
    sys.path.insert(0, str(pathlib.Path(matchedfilter.__file__).parents[2] / "tools"))
    from build_spirv import TIER_B
    assert sorted(int(k) for k in manifest["modules"]) == sorted(TIER_B)


@pytest.mark.parametrize("n", [1024, 2048, 4096, 8192, 16384])
def test_blob_is_valid_spirv(manifest, n):
    blob = (SPIRV_DIR / manifest["modules"][str(n)]["file"]).read_bytes()
    assert len(blob) % 4 == 0, "SPIR-V is a word stream"
    assert struct.unpack("<I", blob[:4])[0] == 0x07230203


@pytest.mark.parametrize("n", [1024, 2048, 4096, 8192, 16384])
def test_workgroup_is_one_sixteenth_of_the_transform(manifest, n):
    """WG = n/16 is the four-step split, not a tuning knob.

    Each thread owns one of the 16 rows' worth of work, so a mismatch here
    means the host would dispatch a grid that does not cover the transform.
    """
    assert manifest["modules"][str(n)]["local_size"][0] == n // 16


@pytest.mark.parametrize("n", [1024, 4096, 16384])
def test_host_binding_contract(manifest, n):
    """What the host must bind, read from the artefact rather than the source.

    The uniform entry-point parameters compile to PUSH CONSTANTS, not to
    further descriptors. A host written from the Slang source would bind
    buffers the module never reads, so this is pinned where it can be seen.
    """
    info = manifest["modules"][str(n)]
    assert [(d["set"], d["binding"]) for d in info["descriptors"]] == [
        (0, 0), (0, 1), (0, 2), (0, 3)]     # data, tmpl, peakIdx, peakVal
    assert all(d["kind"] == "StorageBuffer" for d in info["descriptors"])
    assert info["push_constant"] is True


def test_blobs_match_the_current_kernel_source(manifest, tmp_path):
    """Recompile and compare, so edited source cannot ship as an old blob."""
    import sys
    sys.path.insert(0, str(pathlib.Path(matchedfilter.__file__).parents[2] / "tools"))
    import build_spirv

    slangc = build_spirv.find_slangc()
    if slangc is None:
        pytest.skip("slangc not installed (build-time dependency only)")

    for n_str, info in manifest["modules"].items():
        fresh = build_spirv.compile_one(slangc, int(n_str), tmp_path).read_bytes()
        shipped = (SPIRV_DIR / info["file"]).read_bytes()
        assert fresh == shipped, (
            "%s is stale: src/gpu/%s has changed since it was built. "
            "Re-run tools/build_spirv.py." % (info["file"], manifest["kernel"]))
