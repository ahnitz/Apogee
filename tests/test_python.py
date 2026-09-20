"""Python-level tests for the matched-filter interface.

Checks the class API against numpy, and that the Python layer adds no
measurable cost over the C path - the run loop is one call into C.
"""
import time
import numpy as np
import pytest
import peakfft


def _case(n, D, T, seed=0):
    rng = np.random.default_rng(seed)
    d = (rng.standard_normal((D, n)) + 1j * rng.standard_normal((D, n))).astype(np.complex64)
    h = (rng.standard_normal((T, n)) + 1j * rng.standard_normal((T, n))).astype(np.complex64)
    return d, h


def _ref(d, h):
    """Unnormalised correlation, the same convention the library uses."""
    n = d.size
    return np.fft.ifft(np.fft.fft(d.astype(np.complex128)) *
                       np.conj(np.fft.fft(h.astype(np.complex128)))) * n


@pytest.mark.parametrize("n,D,T", [(1024, 2, 3), (4096, 4, 4), (16384, 2, 2)])
def test_matches_numpy(n, D, T):
    d, h = _case(n, D, T)
    mf = peakfft.MatchedFilter(n, D, T)
    mf.set_data(d)
    mf.set_templates(h)
    bs = n // 4
    peaks = mf.run(binsize=bs)
    assert peaks.shape == (D, T, n // bs)
    for i in range(D):
        for j in range(T):
            z = _ref(d[i], h[j])
            mag = np.abs(z)
            for b in range(peaks.shape[2]):
                lo, hi = b * bs, (b + 1) * bs
                want = lo + int(np.argmax(mag[lo:hi]))
                got = peaks[i, j, b]
                assert got["index"] == want
                assert abs(got["magnitude"] - mag[want]) <= 1e-5 * mag.max()


def test_threshold_and_empty_bins():
    n, bs = 4096, 512
    d, h = _case(n, 1, 1, seed=3)
    mf = peakfft.MatchedFilter(n, 1, 1)
    mf.set_data(d); mf.set_templates(h)
    mag = np.abs(_ref(d[0], h[0]))
    thr = float(np.sort(mag)[::-1][2])
    peaks, counts = mf.run(binsize=bs, threshold=thr, counts=True)
    for b in range(peaks.shape[2]):
        lo, hi = b * bs, (b + 1) * bs
        best = mag[lo:hi].max()
        if best <= thr:
            assert peaks[0, 0, b]["index"] == -1
            assert peaks[0, 0, b]["magnitude"] == 0
    assert counts[0, 0] == int(np.sum(peaks[0, 0]["index"] >= 0))
    # a floor above everything empties every bin
    peaks = mf.run(binsize=bs, threshold=float(mag.max()) * 2)
    assert np.all(peaks["index"] == -1)


def test_window():
    n, bs = 4096, 256
    d, h = _case(n, 1, 1, seed=5)
    mf = peakfft.MatchedFilter(n, 1, 1)
    mf.set_data(d); mf.set_templates(h)
    ws, we = 800, 3000
    peaks = mf.run(binsize=bs, window=(ws, we))
    idx = peaks["index"].ravel()
    assert np.all(idx >= ws) and np.all(idx < we)
    assert peaks.shape[2] == mf.nbins(bs, window=(ws, we))


def test_subrange_matches_full():
    n, D, T, bs = 1024, 4, 4, 256
    d, h = _case(n, D, T, seed=7)
    mf = peakfft.MatchedFilter(n, D, T)
    mf.set_data(d); mf.set_templates(h)
    full = mf.run(binsize=bs)
    sub = mf.run(binsize=bs, data=(1, 2), templates=(2, 2))
    assert np.array_equal(sub["index"], full["index"][1:3, 2:4])


def test_known_lag():
    n, lag = 4096, 321
    rng = np.random.default_rng(11)
    d = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h = np.roll(d, -lag)
    mf = peakfft.MatchedFilter(n, 1, 1)
    mf.set_data(d, index=0); mf.set_templates(h, index=0)
    peaks = mf.run(binsize=n)
    assert peaks[0, 0, 0]["index"] == lag
    energy = float(np.sum(np.abs(d.astype(np.complex128)) ** 2))
    assert abs(peaks[0, 0, 0]["magnitude"] - energy * n) <= 1e-4 * energy * n


def test_shape_errors():
    mf = peakfft.MatchedFilter(1024, 2, 2)
    with pytest.raises(ValueError):
        mf.set_data(np.zeros((3, 1024), dtype=np.complex64))
    with pytest.raises(ValueError):
        mf.run(data=(0, 5))
    with pytest.raises(ValueError):
        mf.run(window=(500, 500))


def test_python_overhead_is_negligible():
    """The pair loop is one call into C, so Python must not show up in the cost."""
    n, D, T = 4096, 8, 8
    d, h = _case(n, D, T, seed=13)
    mf = peakfft.MatchedFilter(n, D, T)
    mf.set_data(d); mf.set_templates(h)
    best_small = best_large = 1e30
    for _ in range(5):
        t0 = time.perf_counter(); mf.run(binsize=1024, data=(0, 1), templates=(0, 1))
        best_small = min(best_small, time.perf_counter() - t0)
        t0 = time.perf_counter(); mf.run(binsize=1024)
        best_large = min(best_large, time.perf_counter() - t0)
    per_pair_small = best_small          # 1 pair, so this is call overhead + 1 pair
    per_pair_large = best_large / (D * T)
    # if Python overhead dominated, one pair would cost far more than the average
    assert per_pair_small < 25 * per_pair_large, (
        f"per-pair cost {per_pair_small*1e6:.1f} us for a single pair vs "
        f"{per_pair_large*1e6:.1f} us amortised - Python overhead is not negligible")
