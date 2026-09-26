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


def _tools_dir():
    """tools/ beside the TESTS, not beside the installed package.

    Using matchedfilter.__file__ works only in a source checkout; against an
    installed wheel the package sits in site-packages and tools/ is nowhere
    near it.
    """
    here = pathlib.Path(__file__).resolve().parent
    for base in (here.parent, here.parent.parent):
        cand = base / "tools"
        if (cand / "build_spirv.py").is_file():
            return cand
    return None


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
    tools = _tools_dir()
    if tools is None:
        pytest.skip("tools/ is not beside the tests (installed package?)")
    sys.path.insert(0, str(tools))
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
    tools = _tools_dir()
    if tools is None:
        pytest.skip("tools/ is not beside the tests (installed package?)")
    sys.path.insert(0, str(tools))
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


def test_every_kernel_has_a_portable_variant_when_it_needs_one(manifest):
    """Anything over 32 KB of workgroup memory must have a fallback.

    Apple allows a threadgroup 32 KB and several kernels are built at 64 KB
    because that is fastest on the development device. Without a smaller
    build those sizes cannot create a pipeline at all there.
    """
    for key, info in manifest["modules"].items():
        if info.get("lds_bytes", 0) > 32768:
            assert "portable" in info, (
                "n=%s asks for %d KB and has no portable variant"
                % (key, info["lds_bytes"] // 1024))
            assert info["portable"]["lds_bytes"] <= 32768
            assert (SPIRV_DIR / info["portable"]["file"]).is_file()


def test_declared_shared_memory_matches_the_kernels_own_arithmetic(manifest):
    """The manifest must not claim a size the shader does not ask for."""
    import sys
    tools = _tools_dir()
    if tools is None:
        pytest.skip("tools/ is not beside the tests (installed package?)")
    sys.path.insert(0, str(tools))
    from build_spirv import lds_bytes, LDS_CAP
    for key, info in manifest["modules"].items():
        n = int(key)
        assert info["lds_bytes"] == lds_bytes(n, LDS_CAP[n])


def test_the_metal_column_is_recorded_and_fits_apple(manifest):
    """Metal is built against its own staging cap, so it must say so.

    The two backends want opposite answers -- CH=16 is a 2.01x win at n=4096
    on an M2 and a 31% loss on a Radeon 8060S -- so the Metal build no longer
    shares LDS_CAP. If metal_lds_bytes went missing, _stem would fall back to
    the Vulkan figure and compare this device's limit against a number no
    Metal kernel was built with: at n=4096 that reads 16 KB where the kernel
    actually asks for 32, which is under Apple's limit by luck rather than by
    check. The direction that bites is a size whose Metal cap is larger than
    its Vulkan one and over 32 KB -- silently no portable variant, and no Mac
    can create the pipeline.
    """
    import sys
    tools = _tools_dir()
    if tools is None:
        pytest.skip("tools/ is not beside the tests (installed package?)")
    sys.path.insert(0, str(tools))
    from build_spirv import lds_bytes, metal_cap
    for key, info in manifest["modules"].items():
        n = int(key)
        assert "metal_lds_bytes" in info, "n=%s has no Metal column" % key
        assert info["metal_lds_bytes"] == lds_bytes(n, metal_cap(n))
        if info["metal_lds_bytes"] > 32768:
            for entry, files in info["metal"].items():
                assert "portable" in files, (
                    "n=%s %s asks Apple for %d KB with no portable build"
                    % (key, entry, info["metal_lds_bytes"] // 1024))
                assert files["portable"]["lds_bytes"] <= 32768


def test_base_coarse_kernels_are_untiled():
    """TILE_T is compiled in, so the BASE coarse kernel must be TILE_T=1.

    The host falls back to an untiled dispatch whenever ntemplates does not
    divide by the tile -- nt=1, 3 and 5 never do. If the base kernel
    carries the band's tile instead of 1, that fallback selects a TILED
    kernel and dispatches for an untiled one. The kernel then walks TILE_T
    consecutive templates from p0 = gid.x*TILE_T, past the end of the
    bank: pairs are never visited and the gate silently drops signal, while
    out-of-range groups write past the output buffer.

    Traced at band 512, nt=2: 4 groups at p0 = 0, 4, 8, 12 with only pairs
    0 and 1 reachable, so half the injections vanished.

    A tiled variant must exist alongside it for every band that has a tile,
    and must be a DIFFERENT kernel -- if they compile identical the tile
    is not reaching the source.
    """
    import matchedfilter as mf
    spv = pathlib.Path(mf.__file__).parent / "spirv"
    if not any(spv.glob("tierb_*_c16.spv")):
        pytest.skip("no coarse kernels in this build")

    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))
    from build_spirv import COARSE_TILE_T
    checked = 0
    for band, tile in COARSE_TILE_T.items():
        base = spv / ("tierb_%d_c16.spv" % band)
        tiled = spv / ("tierb_%d_c16t%d.spv" % (band, tile))
        if not base.exists():
            continue
        assert tiled.exists(), (
            "band %d has tile %d but no %s: the untiled fallback would "
            "select a tiled kernel" % (band, tile, tiled.name))
        assert base.read_bytes() != tiled.read_bytes(), (
            "band %d: base and tiled kernels are identical, so TILE_T is "
            "not reaching the source" % band)
        checked += 1
    assert checked, "no band with a tile was checked"
