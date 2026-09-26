"""Every kernel the library can ask for is present in the install.

A missing kernel is not a build error. build_spirv.py writes what it is
told to write, the package-data globs copy whatever matches, and nothing
compares the two -- so a kernel that stopped being generated, or a new
variant that no glob matched, ships as a wheel that works on the developer's
machine and fails on a device that selects the missing one.

That is not hypothetical. The flat kernel had a 32 KB variant for the two
sizes whose staging wants 64 KB and the refine kernel did not, so a device
offering 32 KB ran the flat path and could not create a hierarchical
pipeline at all. Every GPU used in development has 64 KB, so nothing here
could have noticed.

These check the SHIPPED tree via matchedfilter.__file__, so they hold for
an installed wheel and not only for a source checkout.
"""
import json
import pathlib

import pytest

import matchedfilter as mf


def _dirs():
    root = pathlib.Path(mf.__file__).resolve().parent
    return root / "spirv", root / "metal"


def _manifest():
    spirv, _ = _dirs()
    p = spirv / "manifest.json"
    if not p.is_file():
        pytest.skip("no SPIR-V manifest in this install")
    return json.loads(p.read_text())


def test_every_supported_length_has_a_kernel():
    """_GPU_SIZES is the promise; the manifest has to keep it."""
    man = _manifest()
    for n in sorted(mf._GPU_SIZES):
        assert str(n) in man["modules"], (
            "device='gpu' accepts n=%d but no kernel was built for it" % n)


def test_every_file_the_manifest_names_exists():
    """Including the portable variants, which is where the gap was."""
    spirv, metal = _dirs()
    man = _manifest()
    missing = []
    for n, info in sorted(man["modules"].items(), key=lambda kv: int(kv[0])):
        refine = info.get("refine") or {}
        for f, why in ((info.get("file"), "flat"),
                       ((info.get("portable") or {}).get("file"), "flat 32 KB"),
                       (refine.get("file"), "refine"),
                       ((refine.get("portable") or {}).get("file"), "refine 32 KB")):
            if f and not (spirv / f).is_file():
                missing.append("n=%s %s: %s" % (n, why, f))
        for entry, m in (info.get("metal") or {}).items():
            for f, why in ((m.get("msl"), entry),
                           ((m.get("portable") or {}).get("msl"),
                            entry + " 32 KB")):
                if f and not (metal / f).is_file():
                    missing.append("n=%s metal %s: %s" % (n, why, f))
    assert not missing, "the manifest names kernels that did not ship:\n  " \
        + "\n  ".join(missing)


def test_both_entry_points_have_the_same_variants():
    """The flat and refine kernels run on the same devices, so they need the
    same fallbacks. Having one without the other is the bug this catches."""
    man = _manifest()
    for n, info in sorted(man["modules"].items(), key=lambda kv: int(kv[0])):
        flat_small = bool((info.get("portable") or {}).get("file"))
        refine_small = bool(((info.get("refine") or {}).get("portable") or {})
                           .get("file"))
        assert flat_small == refine_small, (
            "n=%s ships a 32 KB variant for %s only -- a device that needs "
            "one needs both, and will run the flat path and fail to build a "
            "hierarchical pipeline"
            % (n, "the flat kernel" if flat_small else "the refine kernel"))


def test_the_tiled_coarse_kernels_selected_are_present():
    """_COARSE_TILE is consulted at run time; what it names must exist."""
    spirv, _ = _dirs()
    from matchedfilter import _vkcompute as V
    for band in V._COARSE_TILE:
        assert (spirv / ("coarse_%d.spv" % band)).is_file(), (
            "_COARSE_TILE selects band %d but coarse_%d.spv did not ship"
            % (band, band))
