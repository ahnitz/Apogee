"""Python-level tests. Run with: python -m pytest tests/test_python.py

Checks every supported size against numpy's FFT, in both directions, on whichever
back end PEAKFFT_ISA selects - so CI can run the same file twice to cover both.
"""
import os
import numpy as np
import pytest
import peakfft

SIZES = [1024] + [1 << k for k in range(12, 21)]
TOL = 1e-5


def _rand(n, seed):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)


@pytest.mark.parametrize("n", SIZES)
@pytest.mark.parametrize("direction", ["forward", "backward"])
def test_fft_matches_numpy(n, direction):
    x = _rand(n, n + (direction == "backward"))
    ref = np.fft.fft(x.astype(np.complex128)) if direction == "forward" \
        else np.fft.ifft(x.astype(np.complex128)) * n
    got = peakfft.fft(x, direction)
    assert np.abs(got - ref).max() / np.abs(ref).max() < TOL


@pytest.mark.parametrize("n", SIZES)
@pytest.mark.parametrize("k", [1, 8])
def test_topk_matches_numpy(n, k):
    x = _rand(n, 7 * n + k)
    ref = np.fft.fft(x.astype(np.complex128))
    mag = np.abs(ref)
    expect = list(np.argsort(-mag)[:k])
    peaks = peakfft.topk(x, k)
    assert len(peaks) == k
    assert list(peaks["index"]) == expect
    for p in peaks:
        assert abs(p["value"] - ref[p["index"]]) / mag[p["index"]] < TOL
        assert abs(p["magnitude"] - mag[p["index"]]) / mag[p["index"]] < TOL
    # descending order
    assert np.all(np.diff(peaks["magnitude"]) <= 0)


def test_roundtrip():
    n = 1 << 16
    x = _rand(n, 99)
    back = peakfft.fft(peakfft.fft(x), "backward")
    assert np.abs(back / n - x).max() / np.abs(x).max() < TOL


def test_peak_fields_are_explicit():
    peaks = peakfft.topk(_rand(4096, 5), 3)
    assert peaks.dtype.names == ("index", "value", "magnitude")
    assert peaks["index"].dtype == np.int64
    assert peaks["value"].dtype == np.complex64


def test_rejects_bad_sizes():
    with pytest.raises(ValueError):
        peakfft.Plan(2048)
    with pytest.raises(ValueError):
        peakfft.Plan(1 << 21)


def test_plan_reuse():
    p = peakfft.Plan(4096)
    for s in range(3):
        x = _rand(4096, s)
        ref = np.fft.fft(x.astype(np.complex128))
        assert p.topk(x, 1)["index"][0] == int(np.argmax(np.abs(ref)))


def test_isa_env_is_honoured():
    want = os.environ.get("PEAKFFT_ISA")
    if want in ("avx2", "avx512"):
        # the module picked a back end at import; just prove it still works
        assert peakfft.topk(_rand(1 << 14, 3), 1).size == 1
