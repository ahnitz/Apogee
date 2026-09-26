"""The kernel's geometry, checked where it is actually decided.

n = WG * R: a workgroup of WG threads each holding R points.  R is 16 up to
n=16384 and then 32 and 64, because a workgroup is capped at 1024 threads.
R is not one number in one place -- it is compiled into the SPIR-V, mirrored
by the Metal host (which dispatches an explicit threadgroup size), and
assumed by the index mapping.  Three copies that must agree.

None of that fails loudly when it drifts.  A wrong threadgroup size launches
the wrong shape rather than refusing to launch, and a wrong index mapping
reports a real peak at the wrong sample -- both survive a benchmark and a
"does it run" test.  So they are pinned here.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

import matchedfilter as mf                                  # noqa: E402
import build_spirv                                          # noqa: E402
import gpu_regmodel                                         # noqa: E402
import gpu_tierc_model                                      # noqa: E402
from matchedfilter import _mtlcompute                       # noqa: E402

MANIFEST = (pathlib.Path(mf.__file__).parent / "spirv" / "manifest.json")


def test_regmodel_reproduces_every_built_length():
    """The decomposition, end to end, against a float64 reference.

    This is the check that would have caught the two index bugs already in
    this kernel's history, and the one that made widening R tractable: it
    runs the real want[] scatter, the real exchange addressing and the real
    slotToIndex digit reversal, so an error in any of them shows up as a
    register holding the wrong output index rather than as a plausible
    number.
    """
    import numpy as np
    rng = np.random.default_rng(7)
    for n, radix in gpu_regmodel.CASES:
        (wg, nlevels, inner), err = gpu_regmodel.run(n, radix, rng)
        assert err < 1e-11, (
            "n=%d R=%d (WG=%d NLEVELS=%d INNER=%d): register contents "
            "disagree with ifft by %.2e -- the decomposition, the twiddles "
            "or the output order is wrong" % (n, radix, wg, nlevels, inner, err))


def test_the_model_covers_exactly_what_is_built():
    """A length that ships without a modelled case is unchecked above."""
    assert {n for n, _ in gpu_regmodel.CASES} == set(build_spirv.TIER_B)


def test_gpu_sizes_match_the_build():
    """_GPU_SIZES is what device="gpu" checks before building a plan.

    If it disagrees with TIER_B, the library either refuses a length whose
    kernel is sitting in the wheel, or accepts one that is not there and
    fails at pipeline creation instead of at the call.
    """
    assert set(mf._GPU_SIZES) == set(build_spirv.TIER_B)


@pytest.mark.parametrize("n", sorted(set(build_spirv.TIER_B)))
def test_compiled_workgroup_is_n_over_radix(n):
    """What the SPIR-V actually declares, not what the source intended."""
    mods = json.loads(MANIFEST.read_text())["modules"]
    if str(n) not in mods:
        pytest.skip("no module for n=%d" % n)
    radix = build_spirv.RADIX.get(n, 16)
    assert mods[str(n)]["local_size"][0] == n // radix
    assert n // radix <= 1024, (
        "n=%d at R=%d wants %d threads; a workgroup is capped at 1024"
        % (n, radix, n // radix))


@pytest.mark.parametrize("n", sorted(set(build_spirv.TIER_B)))
def test_metal_host_agrees_with_the_compiled_threadgroup(n):
    """Metal dispatches the threadgroup size from the host.

    Vulkan reads it out of the module, so a mismatch there is impossible;
    Metal does not, so this is the only thing standing between a wrong
    RADIX entry and a wrongly shaped launch on Apple hardware.
    """
    mods = json.loads(MANIFEST.read_text())["modules"]
    if str(n) not in mods:
        pytest.skip("no module for n=%d" % n)
    assert n // _mtlcompute._radix(n) == mods[str(n)]["local_size"][0]


#: Tier C is not implemented. The decomposition it will be built from is,
#: and is checked here so the design cannot rot between now and then -- the
#: same order of work that made Tier B safe to write: model first, against a
#: float64 reference, because the kernel's failure mode is silent.
def test_tierc_decomposition_is_correct_before_it_is_written():
    import numpy as np
    rng = np.random.default_rng(1)
    for n in gpu_tierc_model.CASES:
        n1, n2 = gpu_tierc_model.split(n)
        assert n1 * n2 == n
        assert n1 in mf._GPU_SIZES and n2 in mf._GPU_SIZES, (
            "n=%d splits into %d x %d, and a factor Tier B cannot carry "
            "means the split is not usable" % (n, n1, n2))
        x = rng.standard_normal(n) + 1j * rng.standard_normal(n)
        ref = np.fft.ifft(x) * n
        err = np.abs(gpu_tierc_model.tierc(x, n) - ref).max() / np.abs(ref).max()
        assert err < 1e-12, "n=%d: two-stage split disagrees by %.2e" % (n, err)


def test_tierc_index_contract_through_the_real_subtransform():
    """The part of Tier C with no safety net.

    Each stage is a Tier B transform, which leaves its output digit-
    reversed in registers -- so slotToIndex applies TWICE: on k2 leaving
    stage 1, on k1 leaving stage 3. Get either wrong and the kernel
    reports a real peak at the wrong sample, at the right magnitude,
    fast. Nothing downstream notices.

    Checked at the smallest case only: the contract is structural, not
    length-dependent, and the larger ones cost minutes in a Python loop
    for no extra coverage.
    """
    import numpy as np
    n = gpu_tierc_model.CASES[0]
    rng = np.random.default_rng(1)
    x = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    ref = np.fft.ifft(x) * n
    err = np.abs(gpu_tierc_model.tierc_kernels(x, n) - ref).max() / np.abs(ref).max()
    assert err < 1e-12, (
        "n=%d: the two-stage split through the real sub-transform "
        "disagrees by %.2e -- the index mapping, not the arithmetic" % (n, err))


def test_tierc_covers_exactly_the_parity_gap():
    """What the CPU takes and the GPU does not, with nothing left over."""
    cpu_max = 1048576
    cpu = {1 << k for k in range(6, 21) if (1 << k) <= cpu_max}
    assert set(mf._GPU_SIZES) | set(gpu_tierc_model.CASES) == cpu, (
        "Tier B and the Tier C plan do not add up to the CPU's range: "
        "missing %s" % sorted(cpu - set(mf._GPU_SIZES) - set(gpu_tierc_model.CASES)))
