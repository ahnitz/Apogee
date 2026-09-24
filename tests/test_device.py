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
