"""End to end against numpy, starting from the time domain.

The other numpy comparisons feed the filter random spectra directly.  This one
does what a caller does: build a chirp template and noisy data in the time
domain, inject the template at a known lag, take the forward transforms with
numpy, and compare the filter's binned peaks with a float64 numpy matched
filter over the same data.  It also covers the long transforms (up to 2^20),
which the spectrum-level tests do not reach.
"""
import numpy as np
import pytest

import matchedfilter as mf


def chirp(n, f0, f1, rng):
    """Unit-norm complex chirp occupying the first quarter of the segment."""
    m = n // 4
    t = np.arange(m) / n
    phase = 2 * np.pi * n * (f0 * t + 0.5 * (f1 - f0) * t * t / t[-1])
    h = np.zeros(n, dtype=np.complex128)
    h[:m] = np.exp(1j * (phase + rng.uniform(0, 2 * np.pi))) * np.hanning(m)
    return h / np.linalg.norm(h)


def generate(n, nd, nt, lags, amp, seed):
    """Time-domain data (noise + one template at lags[d]) and templates."""
    rng = np.random.default_rng(seed)
    tmpl = np.array([chirp(n, 0.01 + 0.01 * t, 0.2 + 0.02 * t, rng) for t in range(nt)])
    data = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))) / np.sqrt(2)
    for d in range(nd):
        data[d] += amp * np.roll(tmpl[d % nt], lags[d])
    return data, tmpl


def numpy_peaks(dspec, tspec, binsize, threshold):
    """float64 reference: |IFFT(D conj(T))| unnormalised, binned argmax."""
    nd, n = dspec.shape
    z = np.fft.ifft(dspec[:, None, :] * np.conj(tspec[None, :, :]), axis=-1) * n
    mag = np.abs(z).reshape(nd, tspec.shape[0], n // binsize, binsize)
    k = mag.argmax(axis=-1)
    m = np.take_along_axis(mag, k[..., None], -1)[..., 0]
    idx = k + binsize * np.arange(n // binsize)
    idx = np.where(m > threshold, idx, -1)
    return idx, np.where(m > threshold, m, 0.0), np.abs(z)


@pytest.mark.parametrize("n", [1024, 4096, 32768, 262144, 1 << 20])
def test_time_domain_injection_matches_numpy(n):
    nd, nt = 3, 2
    lags = [n // 3, 7, n - 5]
    amp = 12.0
    data, tmpl = generate(n, nd, nt, lags, amp, seed=n)
    # the forward transforms a caller would take, then float32 as the API wants
    dspec = np.fft.fft(data).astype(np.complex64)
    tspec = np.fft.fft(tmpl).astype(np.complex64)

    binsize = n // 16
    # numpy's ifft(D conj(H)) is the circular correlation, which for unit-
    # variance noise and a unit-norm template has unit variance; the filter's
    # output is n times that.  Threshold at SNR 4.
    thr = 4.0 * n

    f = mf.MatchedFilter(n, nd, nt)
    f.set_data(dspec)
    f.set_templates(tspec)
    pk = f.run(binsize=binsize, threshold=thr)

    eidx, emag, full = numpy_peaks(dspec.astype(np.complex128),
                                   tspec.astype(np.complex128), binsize, thr)

    # Where the filter and numpy pick different samples in a bin, the two
    # candidates must be tied to single precision; anything else is a bug.
    got = pk["index"]
    diff = got != eidx
    for d, t, b in zip(*np.nonzero(diff)):
        i, j = got[d, t, b], eidx[d, t, b]
        assert i >= 0 and j >= 0, (d, t, b, i, j)
        assert abs(full[d, t, i] - full[d, t, j]) <= 1e-5 * full[d, t, j]
    assert diff.mean() < 1e-3
    np.testing.assert_allclose(pk["magnitude"], emag, rtol=5e-5,
                               atol=1e-5 * float(emag.max()))

    # The injected signal is found at its lag, at the expected SNR.
    for d in range(nd):
        t = d % nt
        b = lags[d] // binsize
        assert abs(got[d, t, b] - lags[d]) <= 1   # noise can move it a sample
        snr = pk["magnitude"][d, t, b] / n
        assert abs(snr - amp) < 5.0
