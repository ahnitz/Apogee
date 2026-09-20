"""Python-level tests for the matched-filter interface.

Checks the class API against numpy, and that the Python layer adds no
measurable cost over the C path - the run loop is one call into C.
"""
import time
import numpy as np
import pytest
import apogee


def _case(n, D, T, seed=0):
    """Return time-domain segments and their spectra; the library takes spectra."""
    rng = np.random.default_rng(seed)
    d = (rng.standard_normal((D, n)) + 1j * rng.standard_normal((D, n))).astype(np.complex64)
    h = (rng.standard_normal((T, n)) + 1j * rng.standard_normal((T, n))).astype(np.complex64)
    return d, h


def _spec(a):
    return np.fft.fft(a, axis=-1).astype(np.complex64)


def _ref(d, h):
    """Unnormalised correlation, the same convention the library uses."""
    n = d.size
    return np.fft.ifft(np.fft.fft(d.astype(np.complex128)) *
                       np.conj(np.fft.fft(h.astype(np.complex128)))) * n


@pytest.mark.parametrize("n,D,T", [(1024, 2, 3), (4096, 4, 4), (16384, 2, 2)])
def test_matches_numpy(n, D, T):
    d, h = _case(n, D, T)
    mf = apogee.MatchedFilter(n, D, T)
    mf.set_data(_spec(d))
    mf.set_templates(_spec(h))
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
    mf = apogee.MatchedFilter(n, 1, 1)
    mf.set_data(_spec(d)); mf.set_templates(_spec(h))
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
    mf = apogee.MatchedFilter(n, 1, 1)
    mf.set_data(_spec(d)); mf.set_templates(_spec(h))
    ws, we = 800, 3000
    peaks = mf.run(binsize=bs, window=(ws, we))
    idx = peaks["index"].ravel()
    assert np.all(idx >= ws) and np.all(idx < we)
    assert peaks.shape[2] == mf.nbins(bs, window=(ws, we))


def test_subrange_matches_full():
    n, D, T, bs = 1024, 4, 4, 256
    d, h = _case(n, D, T, seed=7)
    mf = apogee.MatchedFilter(n, D, T)
    mf.set_data(_spec(d)); mf.set_templates(_spec(h))
    full = mf.run(binsize=bs)
    sub = mf.run(binsize=bs, data=(1, 2), templates=(2, 2))
    assert np.array_equal(sub["index"], full["index"][1:3, 2:4])


def test_known_lag():
    n, lag = 4096, 321
    rng = np.random.default_rng(11)
    d = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h = np.roll(d, -lag)
    mf = apogee.MatchedFilter(n, 1, 1)
    mf.set_data(_spec(d), index=0); mf.set_templates(_spec(h), index=0)
    peaks = mf.run(binsize=n)
    assert peaks[0, 0, 0]["index"] == lag
    energy = float(np.sum(np.abs(d.astype(np.complex128)) ** 2))
    assert abs(peaks[0, 0, 0]["magnitude"] - energy * n) <= 1e-4 * energy * n


def test_shape_errors():
    mf = apogee.MatchedFilter(1024, 2, 2)
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
    mf = apogee.MatchedFilter(n, D, T)
    mf.set_data(_spec(d)); mf.set_templates(_spec(h))
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


def test_hierarchical_matches_full_filter():
    """The hierarchical filter's peaks must be identical to the full filter's.

    Not close - identical.  When its gate fires it runs the full filter, so any
    difference at all means the gate or the output plumbing is wrong, and a
    tolerance here would hide exactly that.
    """
    n, nd, nt = 1 << 12, 4, 4
    rng = np.random.default_rng(3)
    f = np.arange(n)
    H = np.zeros((nt, n), np.complex64)
    for t in range(nt):
        h = np.zeros(n, complex)
        h[1:n // 2] = np.arange(1, n // 2) ** (-0.9 - 0.05 * t)
        H[t] = (h / np.linalg.norm(h)).astype(np.complex64)
    D = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    for d in range(nd):                      # inject a loud signal so the gate fires
        D[d] += (12.0 * H[0] * np.exp(-2j * np.pi * f * (300 + 17 * d) / n)).astype(np.complex64)

    mf = apogee.MatchedFilter(n, ndata=nd, ntemplates=nt)
    hf = apogee.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=5.5, fd=1e-2)
    for o in (mf, hf):
        o.set_data(D)
        o.set_templates(H)
    a = mf.run(binsize=1024, threshold=5.5)
    b = hf.run(binsize=1024, threshold=5.5)

    fired = b["index"] >= 0
    assert fired.any(), "gate never opened on a 12-sigma signal"
    assert not (fired & (a["index"] < 0)).any(), "reported a peak the full filter did not"
    np.testing.assert_array_equal(a["index"][fired], b["index"][fired])
    np.testing.assert_array_equal(a["value"][fired], b["value"][fired])
    np.testing.assert_array_equal(a["magnitude"][fired], b["magnitude"][fired])

    band, u, k = hf.config
    assert band < n and u in (1, 2) and k >= 2
    assert 0.0 <= hf.trigger_rate <= 1.0


def test_raw_output_matches_structured():
    """raw=True must return exactly what the structured array holds.

    It exists to skip the structured-array assembly for callers driving small
    batches in a tight loop, so it has to be the same numbers -- not merely
    close -- or it becomes a second code path that can silently drift.
    """
    n, nd, nt = 1 << 12, 2, 3
    rng = np.random.default_rng(7)
    D = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    H = (rng.standard_normal((nt, n)) + 1j * rng.standard_normal((nt, n))).astype(np.complex64)
    mf = apogee.MatchedFilter(n, ndata=nd, ntemplates=nt)
    mf.set_data(D)
    mf.set_templates(H)
    peaks = mf.run(binsize=1024, threshold=0.0).copy()
    idx, val, mag = mf.run(binsize=1024, threshold=0.0, raw=True)
    np.testing.assert_array_equal(peaks["index"], idx)
    np.testing.assert_array_equal(peaks["value"], val)
    np.testing.assert_array_equal(peaks["magnitude"], mag)


def test_hierarchical_gate_stays_shut_on_noise():
    """On pure noise nothing should reach the full filter."""
    n = 1 << 12
    rng = np.random.default_rng(11)
    h = np.zeros(n, complex)
    h[1:n // 2] = np.arange(1, n // 2) ** -0.9
    H = (h / np.linalg.norm(h)).astype(np.complex64)
    D = (rng.standard_normal((8, n)) + 1j * rng.standard_normal((8, n))).astype(np.complex64)
    hf = apogee.HierarchicalFilter(n, ndata=8, ntemplates=1, snr=5.5, fd=1e-2)
    hf.set_data(D)
    hf.set_templates(H[None, :])
    peaks = hf.run(binsize=1024, threshold=5.5)
    assert (peaks["index"] < 0).all()
    assert hf.trigger_rate < 0.2
