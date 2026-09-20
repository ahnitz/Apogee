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


@pytest.mark.parametrize("n", [1024, 4096, 1 << 16, 1 << 20])
def test_window(n):
    x = _rand(n, 31 + n)
    ref = np.fft.fft(x.astype(np.complex128))
    mag = np.abs(ref)
    gmax = int(np.argmax(mag))
    windows = [
        (0, n),                       # full
        (n // 4, n // 4 + n // 2),    # middle half
        (n // 3 + 7, n // 3 + 7 + (2 * n) // 3 - 11),   # ragged ~67%
        (gmax + 1, n),                # deliberately excludes the global max
        (gmax, gmax + 1),             # exactly the global max
    ]
    for s, e in windows:
        if s >= e or e > n:
            continue
        k = min(4, e - s)
        peaks = peakfft.topk(x, k, window=(s, e))
        order = [i for i in np.argsort(-mag) if s <= i < e][:k]
        assert list(peaks["index"]) == order, f"window ({s},{e})"
        assert np.all(peaks["index"] >= s) and np.all(peaks["index"] < e)


def test_window_clamped_and_empty():
    x = _rand(4096, 2)
    assert peakfft.topk(x, 4, window=(0, 10**9)).size == 4   # end clamped to n
    assert peakfft.topk(x, 4, window=(100, 100)).size == 0   # empty
    assert peakfft.topk(x, 4, window=(500, 100)).size == 0   # reversed


# --- batched API -----------------------------------------------------------

def _batch_case(n, b, k, direction, thr_quantile):
    rng = np.random.default_rng(n * 131 + b)
    x = (rng.standard_normal((b, n)) + 1j * rng.standard_normal((b, n))).astype(np.complex64)
    sign = 1 if direction == peakfft.BACKWARD else -1
    ref = np.fft.fft(x.astype(np.complex128), axis=1) if sign == -1 \
        else np.fft.ifft(x.astype(np.complex128), axis=1) * n
    mags = np.abs(ref)
    if thr_quantile is None:
        thr = 0.0
    else:
        s = np.sort(mags[0])[::-1]
        q = max(n // thr_quantile, 1)
        thr = float(0.5 * (s[q] + s[q + 1]))
    return x, ref, mags, thr


@pytest.mark.parametrize("n,b,k", [(1024, 16, 8), (1024, 128, 4), (4096, 32, 6),
                                   (16384, 16, 4), (65536, 16, 3)])
@pytest.mark.parametrize("direction", [peakfft.FORWARD, peakfft.BACKWARD])
@pytest.mark.parametrize("thr_q", [None, 1000])
def test_topk_many_matches_numpy(n, b, k, direction, thr_q):
    """Every row must match a brute-force ranking of numpy's spectrum.

    With a floor set this also checks there are no false negatives: the count
    has to be exactly the number of bins numpy puts above the floor, capped at
    k.  A mis-primed threshold shows up as a short row, not a wrong value.
    """
    x, ref, mags, thr = _batch_case(n, b, k, direction, thr_q)
    rows = peakfft.topk_many(x, k, threshold=thr, direction=direction)
    assert len(rows) == b
    for j, peaks in enumerate(rows):
        order = np.argsort(-mags[j], kind="stable")
        expect = [int(i) for i in order[:k] if mags[j][i] > thr]
        assert list(peaks["index"]) == expect
        assert np.all(np.diff(peaks["magnitude"]) <= 0), "rows must be sorted loudest first"
        if len(peaks):
            got = peaks["value"]
            want = ref[j][peaks["index"]]
            rel = np.max(np.abs(got - want) / mags[j][peaks["index"]])
            assert rel < 1e-5, f"relative error {rel:.2e}"
            assert np.all(peaks["magnitude"] > thr)


def test_topk_many_matches_single():
    """The batched call and the single-transform call must agree exactly."""
    n, b, k = 4096, 16, 8
    x, _, _, _ = _batch_case(n, b, k, peakfft.FORWARD, None)
    rows = peakfft.topk_many(x, k)
    for j in range(b):
        one = peakfft.topk(x[j], k)
        assert list(rows[j]["index"]) == list(one["index"])
        assert np.array_equal(rows[j]["value"], one["value"])


def test_topk_many_window():
    n, b, k = 4096, 8, 5
    x, ref, mags, _ = _batch_case(n, b, k, peakfft.FORWARD, None)
    ws, we = n // 5, int(n * 0.7)
    rows = peakfft.topk_many(x, k, window=(ws, we))
    for j, peaks in enumerate(rows):
        assert np.all((peaks["index"] >= ws) & (peaks["index"] < we))
        sub = np.argsort(-mags[j][ws:we], kind="stable")[:k] + ws
        assert list(peaks["index"]) == [int(i) for i in sub]


def test_topk_many_rejects_bad_shape():
    with pytest.raises(ValueError):
        peakfft.topk_many(np.zeros(1024, dtype=np.complex64), 4)
