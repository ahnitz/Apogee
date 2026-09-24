"""Adversarial cases: edges, degenerate inputs, and the ends of the value range.

The existing suite checks that the filter agrees with numpy on ordinary
inputs. These check the places an implementation stops agreeing without
anyone noticing: peaks sitting exactly on a bin or window boundary, bins that
do not divide evenly, amplitudes near the ends of what float32 holds, and
inputs that are degenerate rather than merely unusual.

Every assertion here is against a brute-force numpy reference computed the
same way for every case, so a failure says the kernel disagrees with the
definition rather than with a hand-written expectation.
"""
import numpy as np
import pytest

import matchedfilter as mf


def brute(dspec, tspec, binsize, threshold, ws, we):
    """Reference peaks: IFFT(data * conj(template)), binned argmax, unnormalised."""
    nd, n = dspec.shape
    nt = tspec.shape[0]
    nb = -(-(we - ws) // binsize)
    idx = np.full((nd, nt, nb), -1, dtype=np.int64)
    mag = np.zeros((nd, nt, nb), dtype=np.float64)
    for d in range(nd):
        for t in range(nt):
            z = np.fft.ifft(dspec[d].astype(np.complex128)
                            * np.conj(tspec[t].astype(np.complex128))) * n
            w = np.abs(z[ws:we])
            for b in range(nb):
                seg = w[b * binsize:(b + 1) * binsize]
                if not seg.size:
                    continue
                k = int(np.argmax(seg))
                if seg[k] > threshold:
                    idx[d, t, b] = ws + b * binsize + k
                    mag[d, t, b] = seg[k]
    return idx, mag


def run(dspec, tspec, binsize, threshold, window=None):
    f = mf.MatchedFilter(dspec.shape[1], dspec.shape[0], tspec.shape[0])
    f.set_data(dspec)
    f.set_templates(tspec)
    kw = {} if window is None else {"window": window}
    return f.run(binsize=binsize, threshold=threshold, **kw)


def planted(n, lag, amp=1.0, seed=0, noise=0.0):
    """A template, and data holding one copy of it at `lag`.

    Built in the frequency domain: multiplying by the phase ramp is exactly a
    circular shift of `lag` samples, so the peak lands where intended with no
    interpolation error to argue about.
    """
    rng = np.random.default_rng(seed)
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h /= np.linalg.norm(h)
    ramp = np.exp(-2j * np.pi * lag * np.arange(n) / n)
    d = (amp * h * ramp).astype(np.complex64)
    if noise:
        d = d + (noise * (rng.standard_normal(n)
                          + 1j * rng.standard_normal(n))).astype(np.complex64)
    return d[None, :], h[None, :]


# ------------------------------------------------------------ bin edges

@pytest.mark.parametrize("n,binsize", [(1024, 256), (4096, 512), (2048, 128)])
def test_peak_on_every_bin_boundary(n, binsize):
    """A peak on the first and last lag of each bin lands in the right bin.

    An off-by-one in the binned argmax shows up here and essentially nowhere
    else: in the middle of a bin the answer is right either way.
    """
    nb = n // binsize
    for b in range(nb):
        for lag in (b * binsize, (b + 1) * binsize - 1):
            d, h = planted(n, lag, amp=10.0)
            pk = run(d, h, binsize, 1.0)
            got = int(pk["index"][0, 0, b])
            assert got == lag, ("bin %d of %d, planted %d, got %d"
                                % (b, nb, lag, got))
            # and no other bin claims it
            others = [int(v) for j, v in enumerate(pk["index"][0, 0]) if j != b]
            assert all(v == -1 or abs(v - lag) > binsize for v in others)


def test_peak_at_lag_zero_and_at_the_last_lag():
    """The two lags most likely to be dropped by a loop bound."""
    n = 2048
    for lag in (0, 1, n - 2, n - 1):
        d, h = planted(n, lag, amp=10.0)
        pk = run(d, h, n, 1.0)
        assert int(pk["index"][0, 0, 0]) == lag, lag


# --------------------------------------------------------- window edges

def test_peak_exactly_on_each_window_edge_is_reported():
    n, ws, we = 4096, 1024, 3072
    for lag in (ws, ws + 1, we - 2, we - 1):
        d, h = planted(n, lag, amp=10.0)
        pk = run(d, h, we - ws, 1.0, window=(ws, we))
        assert int(pk["index"][0, 0, 0]) == lag, lag


def test_peak_just_outside_the_window_is_not_reported():
    """The window is a bound, not a hint. A peak outside it must not leak in."""
    n, ws, we = 4096, 1024, 3072
    for lag in (ws - 1, we):
        d, h = planted(n, lag, amp=10.0)
        pk = run(d, h, we - ws, 1.0, window=(ws, we))
        got = int(pk["index"][0, 0, 0])
        assert got == -1 or ws <= got < we, (lag, got)
        assert got != lag, "a peak outside the window was reported"


# --------------------------------------------------------- ragged bins

@pytest.mark.parametrize("n,ws,we,binsize", [
    (4096, 0, 4096, 384),      # 4096 / 384 is not an integer
    (4096, 16, 4000, 512),     # window is not a multiple of binsize
    (2048, 100, 1900, 300),    # neither is aligned to anything
])
def test_bins_that_do_not_divide_evenly(n, ws, we, binsize):
    """The last bin is short. It must still be searched, and only once."""
    rng = np.random.default_rng(3)
    d = (rng.standard_normal((2, n)) + 1j * rng.standard_normal((2, n))).astype(np.complex64)
    h = (rng.standard_normal((2, n)) + 1j * rng.standard_normal((2, n))).astype(np.complex64)
    pk = run(d, h, binsize, 0.0, window=(ws, we))
    eidx, emag = brute(d, h, binsize, 0.0, ws, we)
    assert pk["index"].shape == eidx.shape
    assert np.array_equal(pk["index"], eidx)
    assert np.allclose(np.abs(pk["value"]), emag, rtol=2e-5, atol=1e-5)


# -------------------------------------------------------- value ranges

@pytest.mark.parametrize("amp", [1e-12, 1e-6, 1.0, 1e6, 1e12])
def test_amplitude_scale_does_not_change_which_lag_wins(amp):
    """Scaling the data scales the output and moves nothing.

    Run over twelve orders of magnitude. A kernel that squares magnitudes in
    float32 without care loses the small end to underflow and the large end to
    overflow, and in both cases the reported INDEX goes wrong rather than just
    the value -- which is the failure that would be missed.
    """
    n, lag = 2048, 733
    d, h = planted(n, lag, amp=amp)
    pk = run(d, h, n, 0.0)
    assert int(pk["index"][0, 0, 0]) == lag, amp
    m = float(np.abs(pk["value"])[0, 0, 0])
    assert np.isfinite(m), amp
    assert m == pytest.approx(amp, rel=1e-3), amp


def test_templates_of_wildly_different_scale_in_one_batch():
    """One batch, amplitudes spanning 1e-9 to 1e9. Each pair judged on its own."""
    n = 1024
    rng = np.random.default_rng(5)
    scales = np.array([1e-9, 1e-3, 1.0, 1e3, 1e9], dtype=np.float64)
    h = (rng.standard_normal((5, n)) + 1j * rng.standard_normal((5, n)))
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    h = (h * scales[:, None]).astype(np.complex64)
    d = (rng.standard_normal((2, n)) + 1j * rng.standard_normal((2, n))).astype(np.complex64)
    pk = run(d, h, n, 0.0)
    eidx, emag = brute(d, h, n, 0.0, 0, n)
    assert np.array_equal(pk["index"], eidx)
    assert np.allclose(np.abs(pk["value"]), emag, rtol=1e-4)


# ------------------------------------------------------- degenerate input

def test_all_zero_data_reports_nothing_above_a_positive_threshold():
    n = 1024
    d = np.zeros((1, n), np.complex64)
    h = np.ones((1, n), np.complex64)
    pk = run(d, h, n, 1e-6)
    assert int(pk["index"][0, 0, 0]) == -1
    assert float(np.abs(pk["value"])[0, 0, 0]) == 0.0


def test_all_zero_template_is_not_a_crash_or_a_nan():
    n = 1024
    rng = np.random.default_rng(7)
    d = (rng.standard_normal((1, n)) + 1j * rng.standard_normal((1, n))).astype(np.complex64)
    h = np.zeros((1, n), np.complex64)
    pk = run(d, h, n, 0.0)
    assert np.all(np.isfinite(np.abs(pk["value"])))
    assert float(np.abs(pk["value"])[0, 0, 0]) == 0.0


def test_single_nonzero_frequency_bin():
    """A one-bin spectrum correlates to a flat magnitude across every lag.

    So this is the all-ties case, and the point is what is NOT promised:
    which of n equal maxima gets reported is unspecified. numpy's argmax takes
    the first, the kernel takes whichever its scan order reaches -- 219 and
    481 on this input. Both are correct. Pinning the index here would be
    pinning an implementation detail, so what is checked is that the reported
    magnitude is the maximum and the reported lag actually attains it.
    """
    n = 1024
    d = np.zeros((1, n), np.complex64)
    h = np.zeros((1, n), np.complex64)
    d[0, 7] = 1.0
    h[0, 7] = 1.0
    pk = run(d, h, n, 0.0)
    z = np.fft.ifft(d[0].astype(np.complex128) * np.conj(h[0].astype(np.complex128))) * n
    w = np.abs(z)
    got_i = int(pk["index"][0, 0, 0])
    got_m = float(np.abs(pk["value"])[0, 0, 0])
    assert 0 <= got_i < n
    assert got_m == pytest.approx(float(w.max()), rel=1e-5)
    assert w[got_i] == pytest.approx(float(w.max()), rel=1e-5), "reported lag is not a maximum"


def test_threshold_exactly_at_the_peak_magnitude():
    """The comparison is strict, and `magnitude` is the number it used.

    This is why `magnitude` is reported rather than left to abs(value):
    recomputing it can land a few ULP either side of the threshold.
    """
    n, lag = 1024, 300
    d, h = planted(n, lag, amp=4.0)
    pk = run(d, h, n, 0.0)
    m = float(np.abs(pk["value"])[0, 0, 0])
    # One float32 ULP, not one float64 ULP: the threshold crosses a float32
    # interface, so np.nextafter on a Python float asks for a distinction the
    # argument cannot carry and rounds straight back to m.
    below = float(np.nextafter(np.float32(m), np.float32(0.0)))
    assert below < m
    assert int(run(d, h, n, below)["index"][0, 0, 0]) == lag
    assert int(run(d, h, n, m)["index"][0, 0, 0]) == -1, "comparison must be strict"


# ----------------------------------------------------------- batch shapes

@pytest.mark.parametrize("nd,nt", [(1, 1), (1, 17), (17, 1), (3, 5), (13, 7)])
def test_odd_batch_shapes_agree_with_numpy(nd, nt):
    """Counts that are not multiples of any lane width."""
    n = 1024
    rng = np.random.default_rng(nd * 100 + nt)
    d = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    h = (rng.standard_normal((nt, n)) + 1j * rng.standard_normal((nt, n))).astype(np.complex64)
    pk = run(d, h, 256, 0.0)
    eidx, emag = brute(d, h, 256, 0.0, 0, n)
    assert np.array_equal(pk["index"], eidx)
    assert np.allclose(np.abs(pk["value"]), emag, rtol=2e-5, atol=1e-6)


@pytest.mark.parametrize("n", [1024, 2048, 4096, 8192, 16384])
def test_every_supported_length_agrees_with_numpy(n):
    """Sweep the lengths, since each may take a different transform split."""
    rng = np.random.default_rng(n)
    d = (rng.standard_normal((2, n)) + 1j * rng.standard_normal((2, n))).astype(np.complex64)
    h = (rng.standard_normal((2, n)) + 1j * rng.standard_normal((2, n))).astype(np.complex64)
    bs = max(64, n // 8)
    pk = run(d, h, bs, 0.0)
    eidx, emag = brute(d, h, bs, 0.0, 0, n)
    assert np.array_equal(pk["index"], eidx)
    assert np.allclose(np.abs(pk["value"]), emag, rtol=3e-5, atol=1e-6)


def test_binsize_one_reports_every_lag():
    """The degenerate binning: one bin per lag, so the filter reports everything."""
    n = 1024
    rng = np.random.default_rng(11)
    d = (rng.standard_normal((1, n)) + 1j * rng.standard_normal((1, n))).astype(np.complex64)
    h = (rng.standard_normal((1, n)) + 1j * rng.standard_normal((1, n))).astype(np.complex64)
    pk = run(d, h, 1, 0.0)
    assert pk["index"].shape == (1, 1, n)
    assert np.array_equal(pk["index"][0, 0], np.arange(n))
    z = np.fft.ifft(d[0].astype(np.complex128) * np.conj(h[0].astype(np.complex128))) * n
    assert np.allclose(np.abs(pk["value"])[0, 0], np.abs(z), rtol=3e-5, atol=1e-6)


def test_the_selection_cliff_reports_nothing_rather_than_the_wrong_sample():
    """The peak scan selects on |v|^2 in float32, and squaring halves the range.

    The smallest float32 subnormal is 1.4e-45, so |v|^2 flushes to zero once
    |v| falls below its square root -- about 3.7e-23 -- while `value` itself
    is representable for another seventeen orders of magnitude. Below that
    cliff every candidate in the bin compares equal at zero.

    What must NOT happen is reporting the first sample as though it were the
    peak. There used to be a `magnitude` field, and its flushing to zero was
    what warned a caller that the accompanying index meant nothing. With the
    field gone that warning has to live in the index, so a maximum of exactly
    zero falls through to index -1 -- the same "nothing here" the threshold
    path already uses.

    Matched filter inputs are normally O(1), so nothing real is near this. It
    is pinned so a change to the scan moves it deliberately.
    """
    n, lag = 1024, 321
    rng = np.random.default_rng(8)
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h /= np.linalg.norm(h)
    ramp = np.exp(-2j * np.pi * lag * np.arange(n) / n)

    def at(scale):
        d = (np.float32(scale) * h * ramp).astype(np.complex64)
        f = mf.MatchedFilter(n, 1, 1)
        f.set_data(d[None, :])
        f.set_templates(h[None, :])
        pk = f.run(binsize=n, threshold=0.0)
        return int(pk["index"][0, 0, 0]), complex(pk["value"][0, 0, 0])

    i, v = at(1e-20)
    assert i == lag, "well above the cliff the peak is found"
    assert abs(v) == pytest.approx(1e-20, rel=1e-2)

    i, v = at(1e-24)
    assert i == -1, "below the cliff nothing is reported..."
    assert v == 0, "...and no value is offered for a sample that was not chosen"
