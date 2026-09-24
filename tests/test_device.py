"""The device API, exercised the way a user would reach it.

Everything here goes through ``import matchedfilter`` and the public
constructor.  Tests that drive the internal spike runner prove the kernels
work; they do not prove anyone can *get* to them, which is a separate and
easier thing to break.
"""
import numpy as np
import pytest

import matchedfilter as mf


def test_devices_always_lists_a_cpu():
    found = mf.devices()
    assert [d for d in found if d.kind == "cpu"], found
    cpu = [d for d in found if d.kind == "cpu"][0]
    assert cpu.index == 0
    assert cpu.backend in mf.targets() or cpu.backend == mf.backend()


def test_device_prints_and_compares_like_torch():
    cpu = mf.devices()[0]
    assert str(cpu) == "cpu:0"
    assert cpu == "cpu"          # bare kind resolves to the first of that kind
    assert cpu == "cpu:0"
    assert cpu != "gpu:0"


def test_default_is_cpu_even_when_a_gpu_exists():
    """Never dispatch somewhere the caller did not name.

    A GPU changes numerics and failure modes; inheriting one because the
    machine happens to have it is a surprise, not a convenience.
    """
    assert mf.MatchedFilter(1024).device.kind == "cpu"


def test_mf_device_env_override(monkeypatch):
    monkeypatch.setenv("MF_DEVICE", "cpu:0")
    assert mf.MatchedFilter(1024).device == "cpu:0"


@pytest.mark.parametrize("spec", ["tpu", "gpu:x", "cpu:9"])
def test_bad_device_names_are_rejected(spec):
    with pytest.raises(ValueError):
        mf.MatchedFilter(1024, device=spec)


def test_non_string_device_is_a_type_error():
    with pytest.raises(TypeError):
        mf.MatchedFilter(1024, device=0)


# ---- DLPack ingest ---------------------------------------------------------

def _pair(n, seed=3):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)


def test_accepts_any_dlpack_producer():
    """numpy 2 arrays go in over DLPack, not over numpy-specific code.

    The point is that the path is generic: torch, cupy and jax arrive the
    same way, so this keeps working for libraries matchedfilter does not
    import and has never heard of.
    """
    n = 1024
    x = _pair(n)
    assert hasattr(x, "__dlpack__")
    filt = mf.MatchedFilter(n)
    filt.set_data(x, index=0)
    filt.set_templates(x, index=0)
    peak = filt.run()[0, 0, 0]
    assert np.abs(peak["value"]) == pytest.approx(float(n * np.mean(np.abs(x) ** 2)), rel=1e-3)


def test_accelerator_resident_input_is_refused_not_copied():
    """A device-to-host copy here would be silent and would dominate runtime.

    Reported rather than absorbed: an array on a GPU reaching the CPU
    backend means the caller built the wrong filter, and hiding that costs
    them the performance they came for.
    """
    class OnCuda:
        def __dlpack_device__(self):
            return (2, 0)                      # kDLCUDA
        def __dlpack__(self, *a, **k):
            raise AssertionError("must not be reached")

    filt = mf.MatchedFilter(1024)
    with pytest.raises(TypeError, match="CUDA"):
        filt.set_data(OnCuda(), index=0)


def test_objects_without_dlpack_still_work():
    """The buffer / __array__ path predates DLPack and must not regress."""
    n, x = 1024, _pair(1024)

    class Legacy:
        def __array__(self, dtype=None, copy=None):
            return x

    filt = mf.MatchedFilter(n)
    filt.set_data(Legacy(), index=0)
    filt.set_templates(Legacy(), index=0)
    assert abs(filt.run()[0, 0, 0]["value"]) > 0


def test_auto_is_not_vulkan_specific():
    """'auto' means "a GPU if this machine has one", not "if Vulkan does".

    It used to ask _vulkan.available() directly, so on macOS -- which has
    no Vulkan driver and a perfectly good Metal one -- it silently chose the
    CPU. Not having to know which backend your machine uses is the whole
    point of asking for 'auto'.
    """
    import matchedfilter as mf
    from matchedfilter import device as D

    real = [d for d in mf.devices() if d.kind == "gpu" and not d.is_software]
    got = D.parse("auto")
    if real:
        assert got.kind == "gpu", (
            "this machine has %s but 'auto' chose %s" % (real[0], got))
        assert not got.is_software
    else:
        assert got.kind == "cpu"


def test_auto_picks_a_metal_gpu_when_that_is_the_only_backend(monkeypatch):
    """The macOS case, on any machine: Vulkan absent, Metal present."""
    from matchedfilter import device as D

    metal_gpu = D.Device("gpu", 0, "Apple Paravirtual device", "metal")
    cpu = D.Device("cpu", 0, "arm", "NEON")
    monkeypatch.setattr(D, "devices", lambda: [cpu, metal_gpu])
    monkeypatch.setattr(D._vulkan, "available", lambda: (False, "no libvulkan"))
    got = D.parse("auto")
    assert got.backend == "metal" and got.kind == "gpu", (
        "'auto' chose %r with a Metal GPU available" % (got,))


def test_no_gpu_says_why_in_the_platform_s_own_terms(monkeypatch):
    """On a Mac, 'no libvulkan' is a non-answer about whether a GPU exists."""
    import sys
    from matchedfilter import device as D

    monkeypatch.setattr(D, "devices",
                        lambda: [D.Device("cpu", 0, "arm", "NEON")])
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(D._metal, "available",
                        lambda: (False, "no Metal device"))
    with pytest.raises(RuntimeError) as e:
        D.parse("gpu")
    assert "Metal" in str(e.value) and "libvulkan" not in str(e.value)
