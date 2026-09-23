"""The Apple GPU back end, against numpy and against the CPU filter.

Every case runs the same inputs through matchedfilter.metal.MatchedFilter and
compares with (a) a float64 numpy matched filter and (b) the CPU
matchedfilter.MatchedFilter.  The GPU evaluates the transform in a different
order from both, so values agree to single precision rather than bit for bit,
and where two lags in a bin are equal to within rounding either may be
reported; `assert_peaks_match` allows exactly that and nothing more.

Skipped where there is no Metal device, or the build has no GPU back end.
"""
import numpy as np
import pytest

import matchedfilter as mf
from matchedfilter import metal

pytestmark = pytest.mark.skipif(not metal.available(),
                                reason="no Metal GPU back end on this machine")


# ------------------------------------------------------------- helpers

def spectra(shape, seed):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)).astype(np.complex64)


def full_output(D, H):
    """|IFFT(D conj(H))| unnormalised, float64, shape (nd, nt, n)."""
    n = D.shape[1]
    z = np.fft.ifft(D[:, None].astype(np.complex128)
                    * np.conj(H[None].astype(np.complex128)), axis=-1) * n
    return z


def numpy_peaks(z, binsize, threshold, ws, we):
    a = np.abs(z)
    nb = -(-(we - ws) // binsize)
    idx = np.full(a.shape[:2] + (nb,), -1, dtype=np.int64)
    mag = np.zeros(idx.shape)
    for b in range(nb):
        s, e = ws + b * binsize, min(ws + (b + 1) * binsize, we)
        k = a[..., s:e].argmax(-1)
        m = np.take_along_axis(a[..., s:e], k[..., None], -1)[..., 0]
        hit = m > threshold if threshold > 0 else np.ones(m.shape, bool)
        idx[..., b] = np.where(hit, s + k, -1)
        mag[..., b] = np.where(hit, m, 0.0)
    return idx, mag


def assert_peaks_match(got, idx, mag, z, rtol=2e-5, threshold=None):
    """Same peaks as the reference, up to single-precision ties.

    Two disagreements are allowed, and only when rounding explains them: two
    lags in a bin whose magnitudes agree to `rtol`, and a bin that crossed on
    one side only because its peak sits within `rtol` of the threshold.
    """
    gi = got["index"]
    a = np.abs(z)
    scale = float(a.max()) if a.size else 1.0
    edge = np.zeros(gi.shape, bool)
    for d, t, b in np.argwhere(gi != idx):
        i, j = gi[d, t, b], idx[d, t, b]
        if i < 0 or j < 0:
            k = max(i, j)
            assert threshold is not None and \
                abs(a[d, t, k] - threshold) <= rtol * threshold, \
                ("crossing disagrees", (d, t, b), i, j)
            edge[d, t, b] = True
            continue
        assert abs(a[d, t, i] - a[d, t, j]) <= rtol * a[d, t, j] + 1e-6 * scale, \
            ("different lags that are not tied", (d, t, b), i, j)
    np.testing.assert_allclose(got["magnitude"][~edge], mag[~edge], rtol=rtol,
                               atol=1e-6 * scale)
    hit = gi >= 0
    ref = np.take_along_axis(z, np.where(hit, gi, 0), -1)
    np.testing.assert_allclose(got["value"][hit], ref[hit], rtol=0,
                               atol=rtol * scale)
    assert np.all(got["value"][~hit] == 0)


def gpu(D, H):
    f = metal.MatchedFilter(D.shape[1], D.shape[0], H.shape[0])
    f.set_data(D)
    f.set_templates(H)
    return f


# ------------------------------------------------------------- lengths

# one-pass kernel up to 4096, four-step above
LENGTHS = [256, 512, 1024, 2048, 4096, 8192, 16384, 65536, 262144]


@pytest.mark.parametrize("n", LENGTHS)
def test_every_length_agrees_with_numpy(n):
    D, H = spectra((3, n), n), spectra((4, n), n + 1)
    z = full_output(D, H)
    f = gpu(D, H)
    for bs in (n, n // 16, 7):
        idx, mag = numpy_peaks(z, bs, 0.0, 0, n)
        assert_peaks_match(f.run(binsize=bs, threshold=0.0), idx, mag, z)


@pytest.mark.parametrize("n", [1 << 20, 1 << 21])
def test_longest_lengths(n):
    D, H = spectra((1, n), 1), spectra((2, n), 2)
    z = full_output(D, H)
    f = gpu(D, H)
    bs = n // 8
    idx, mag = numpy_peaks(z, bs, 0.0, 0, n)
    assert_peaks_match(f.run(binsize=bs, threshold=0.0), idx, mag, z)


@pytest.mark.parametrize("n", [100, 1000, 128, 1 << 22])
def test_unsupported_lengths_are_refused(n):
    with pytest.raises(ValueError):
        metal.MatchedFilter(n, 1, 1)


# ------------------------------------------------------ bins, windows

@pytest.mark.parametrize("n", [1024, 4096, 16384])
@pytest.mark.parametrize("bs", [1, 3, 32, 33, 64, 100, 128, 129, 1000, 4096])
def test_bin_sizes(n, bs):
    """Every regime of both peak searches: lanes per bin, chunked, runs."""
    D, H = spectra((2, n), 7), spectra((3, n), 8)
    z = full_output(D, H)
    idx, mag = numpy_peaks(z, min(bs, n), 0.0, 0, n)
    assert_peaks_match(gpu(D, H).run(binsize=bs, threshold=0.0), idx, mag, z)


@pytest.mark.parametrize("n", [2048, 32768])
@pytest.mark.parametrize("window", [(0, 1), (5, 6), (3, 1500), (17, 2047), (1000, 2048)])
@pytest.mark.parametrize("bs", [1, 50, 256, 5000])
def test_windows(n, window, bs):
    D, H = spectra((2, n), 9), spectra((2, n), 10)
    z = full_output(D, H)
    ws, we = window
    idx, mag = numpy_peaks(z, bs, 0.0, ws, we)
    assert_peaks_match(gpu(D, H).run(binsize=bs, threshold=0.0, window=window),
                       idx, mag, z)


@pytest.mark.parametrize("n", [4096, 65536])
@pytest.mark.parametrize("q", [0.5, 0.99, 0.9999, 1.0])
def test_thresholds(n, q):
    """Bins below the threshold come back as index -1 with zeros; counts agree."""
    D, H = spectra((2, n), 11), spectra((3, n), 12)
    z = full_output(D, H)
    thr = float(np.quantile(np.abs(z), q))
    bs = n // 64
    idx, mag = numpy_peaks(z, bs, thr, 0, n)
    peaks, counts = gpu(D, H).run(binsize=bs, threshold=thr, counts=True)
    assert_peaks_match(peaks, idx, mag, z, threshold=thr)
    assert np.array_equal(counts, (peaks["index"] >= 0).sum(-1))


def test_threshold_is_strict():
    n = 4096
    D, H = spectra((1, n), 13), spectra((1, n), 14)
    f = gpu(D, H)
    m = float(f.run(binsize=n, threshold=0.0)["magnitude"][0, 0, 0])
    below = float(np.nextafter(np.float32(m), np.float32(0.0)))
    assert f.run(binsize=n, threshold=below)["index"][0, 0, 0] >= 0
    assert f.run(binsize=n, threshold=m)["index"][0, 0, 0] == -1


# ------------------------------------------------------ against the CPU

@pytest.mark.parametrize("n", [1024, 4096, 16384, 131072])
def test_agrees_with_cpu_filter(n):
    """The GPU is a drop-in for the CPU filter on common, non-zero data."""
    nd, nt = 4, 6
    D, H = spectra((nd, n), 15), spectra((nt, n), 16)
    z = full_output(D, H)
    thr = float(np.quantile(np.abs(z), 0.999))
    kw = dict(binsize=n // 32, threshold=thr, window=(11, n - 13))
    cpu = mf.MatchedFilter(n, nd, nt)
    cpu.set_data(D)
    cpu.set_templates(H)
    c = cpu.run(**kw)
    g = gpu(D, H).run(**kw)
    assert_peaks_match(g, c["index"], c["magnitude"].astype(np.float64), z,
                       rtol=3e-5, threshold=thr)


# ------------------------------------------------------ batch structure

@pytest.mark.parametrize("n", [1024, 8192])
@pytest.mark.parametrize("nd,nt", [(1, 1), (1, 17), (17, 1), (3, 5), (13, 7)])
def test_odd_batch_shapes(n, nd, nt):
    D, H = spectra((nd, n), nd), spectra((nt, n), 100 + nt)
    z = full_output(D, H)
    idx, mag = numpy_peaks(z, 256, 0.0, 0, n)
    assert_peaks_match(gpu(D, H).run(binsize=256, threshold=0.0), idx, mag, z)


@pytest.mark.parametrize("n", [2048, 16384])
def test_sub_block_is_the_slice_of_the_whole(n):
    nd, nt = 5, 7
    D, H = spectra((nd, n), 17), spectra((nt, n), 18)
    f = gpu(D, H)
    full = f.run(binsize=512, threshold=0.0).copy()
    part = f.run(binsize=512, threshold=0.0, data=(1, 3), templates=(2, 4))
    np.testing.assert_array_equal(part, full[1:4, 2:6])


@pytest.mark.parametrize("dinner", ["0", "1"])
@pytest.mark.parametrize("n", [1024, 16384])
def test_either_pair_order_gives_the_same_rows(monkeypatch, dinner, n):
    """Execution order is a cache choice; the output layout must not follow it."""
    monkeypatch.setenv("MF_METAL_DINNER", dinner)
    D, H = spectra((3, n), 19), spectra((5, n), 20)
    z = full_output(D, H)
    idx, mag = numpy_peaks(z, n // 4, 0.0, 0, n)
    assert_peaks_match(gpu(D, H).run(binsize=n // 4, threshold=0.0), idx, mag, z)


def test_many_pairs_through_a_small_scratch(monkeypatch):
    """The four-step path runs a large batch as several scratch fills."""
    monkeypatch.setenv("MF_METAL_SCRATCH_MB", "1")
    n = 65536                     # 512 KiB per pair: two pairs per fill
    D, H = spectra((3, n), 21), spectra((3, n), 22)
    z = full_output(D, H)
    idx, mag = numpy_peaks(z, 4096, 0.0, 0, n)
    assert_peaks_match(gpu(D, H).run(binsize=4096, threshold=0.0), idx, mag, z)


def test_ingest_one_at_a_time_and_reingest():
    n = 4096
    D, H = spectra((2, n), 23), spectra((2, n), 24)
    f = metal.MatchedFilter(n, 2, 2)
    for i in range(2):
        f.set_data(D[i], index=i)
        f.set_templates(H[i], index=i)
    a = f.run(binsize=n, threshold=0.0).copy()
    f.set_templates(H[::-1])
    b = f.run(binsize=n, threshold=0.0)
    np.testing.assert_array_equal(a[:, ::-1], b)


# ------------------------------------------------------ degenerate inputs

def test_zero_data_reports_nothing_above_a_threshold():
    n = 4096
    f = gpu(np.zeros((2, n), np.complex64), spectra((2, n), 25))
    pk = f.run(binsize=256, threshold=1e-3)
    assert np.all(pk["index"] == -1) and np.all(pk["magnitude"] == 0)


def test_zero_template_with_no_threshold_reports_lag_zero_not_nan():
    n = 16384
    f = gpu(spectra((1, n), 26), np.zeros((1, n), np.complex64))
    pk = f.run(binsize=1024, threshold=0.0)
    assert np.all(np.isfinite(pk["magnitude"]))
    assert np.array_equal(pk["index"][0, 0], np.arange(0, n, 1024))


@pytest.mark.parametrize("n", [4096, 65536])
def test_planted_signal_on_every_bin_edge(n):
    """A delta correlation placed on the first and last lag of each bin."""
    bs = n // 8
    h = spectra((1, n), 28)[0]
    lags = [b * bs for b in range(8)] + [b * bs + bs - 1 for b in range(8)]
    for lag in lags:
        d = (h * np.exp(-2j * np.pi * lag * np.arange(n) / n)).astype(np.complex64)
        pk = gpu(d[None], h[None]).run(binsize=bs, threshold=0.0)
        assert pk["index"][0, 0, lag // bs] == lag


@pytest.mark.parametrize("n", [4096, 1 << 20])
def test_time_domain_injection(n):
    """What a caller does: chirp in noise, numpy forward FFTs, then filter."""
    rng = np.random.default_rng(29)
    m = n // 4
    t = np.arange(m) / n
    chirp = np.zeros(n, complex)
    chirp[:m] = np.exp(2j * np.pi * n * (0.01 * t + 2.0 * t * t)) * np.hanning(m)
    chirp /= np.linalg.norm(chirp)
    lag = n // 3
    data = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2)
    data += 12.0 * np.roll(chirp, lag)
    D = np.fft.fft(data).astype(np.complex64)[None]
    H = np.fft.fft(chirp).astype(np.complex64)[None]
    pk = gpu(D, H).run(binsize=n // 16, threshold=4.0 * n)
    b = lag // (n // 16)
    assert abs(int(pk["index"][0, 0, b]) - lag) <= 1
    assert abs(pk["magnitude"][0, 0, b] / n - 12.0) < 5.0
