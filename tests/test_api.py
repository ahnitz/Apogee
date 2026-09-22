"""Tests for matchedfilter's public API.

Everything reachable from Python lives here.  The one exception is
tests/test_units.c, which checks the generated codelets, the transpose and the
int16 kernels directly -- those are internal and there is no way to reach them
through MatchedFilter or HierarchicalFilter.

The hierarchical tests are written around a single idea: the guarantee is
one-sided.  A reported peak must be bit-identical to the ungated filter's,
because when the gate fires it runs that filter.  Only omissions are allowed,
and only at the calibrated rate.  Tests that assert closeness rather than
identity would pass while the refinement path quietly diverged, so they assert
identity.
"""
import time

import os
import numpy as np
import pytest

import matchedfilter as mf


# ---------------------------------------------------------------- helpers

def inspiral_power(n, exponent=-7 / 3.0):
    """|h|^2/S for an inspiral-like signal: steeply falling, one-sided."""
    p = np.zeros(n, dtype=np.float32)
    k = np.arange(1, n // 2)
    p[1:n // 2] = (k.astype(np.float64) ** exponent).astype(np.float32)
    return p / p.sum()


def template_with_power(n, power):
    """Unit-norm template whose per-bin power follows `power` (zero phase)."""
    h = np.zeros(n, dtype=np.complex64)
    h[:] = np.sqrt(power).astype(np.complex64)
    return h / np.linalg.norm(h)


def noise(shape, rng):
    return (rng.standard_normal(shape)
            + 1j * rng.standard_normal(shape)).astype(np.complex64)


def brute_peak(data, template, start, end):
    """Reference correlation by numpy, for one (data, template) pair."""
    rho = np.fft.ifft(data * np.conj(template)) * len(data)
    w = np.abs(rho[start:end])
    i = int(np.argmax(w))
    return start + i, rho[start + i]


# ---------------------------------------------------------------- basics

@pytest.mark.parametrize("n", [1024, 4096, 16384])
def test_matches_numpy(n):
    """The filter is IFFT(data * conj(template)), unnormalised."""
    rng = np.random.default_rng(0)
    D, H = noise((3, n), rng), noise((2, n), rng)
    filt = mf.MatchedFilter(n, ndata=3, ntemplates=2)
    filt.set_data(D)
    filt.set_templates(H)
    peaks = filt.run(binsize=n, threshold=0.0)
    for d in range(3):
        for t in range(2):
            idx, val = brute_peak(D[d], H[t], 0, n)
            assert peaks["index"][d, t, 0] == idx
            assert abs(peaks["value"][d, t, 0] - val) < 1e-3 * abs(val)


def test_known_lag():
    """A template that is a circular shift of the data peaks at that lag.

    Sign convention: the filter is IFFT(D * conj(H)), so a template built as
    D * exp(+2i pi f lag/n) puts the peak at `lag`.  The other sign puts it at
    n - lag, which is a correct answer to a different question.
    """
    n = 4096
    rng = np.random.default_rng(1)
    x = noise(n, rng)
    for lag in (0, 1, 37, n // 2, n - 1):
        shifted = x * np.exp(2j * np.pi * np.arange(n) * lag / n)
        filt = mf.MatchedFilter(n, ndata=1, ntemplates=1)
        filt.set_data(x[None, :])
        filt.set_templates(shifted[None, :])
        peaks = filt.run(binsize=n, threshold=0.0)
        assert peaks["index"][0, 0, 0] == lag


def test_bins_and_threshold():
    """One peak per bin; a bin that does not cross reports index -1."""
    n = 4096
    rng = np.random.default_rng(2)
    D, H = noise((1, n), rng), noise((1, n), rng)
    filt = mf.MatchedFilter(n, ndata=1, ntemplates=1)
    filt.set_data(D)
    filt.set_templates(H)
    rho = np.abs(np.fft.ifft(D[0] * np.conj(H[0])) * n)
    thr = float(np.quantile(rho, 0.999))
    peaks = filt.run(binsize=512, threshold=thr)
    assert peaks.shape == (1, 1, n // 512)
    for b in range(n // 512):
        seg = rho[b * 512:(b + 1) * 512]
        if seg.max() > thr:
            assert peaks["index"][0, 0, b] == b * 512 + int(np.argmax(seg))
        else:
            assert peaks["index"][0, 0, b] == -1


def test_window_and_subrange():
    """A window restricts lags; a sub-block equals the matching slice."""
    n, nd, nt = 4096, 4, 3
    rng = np.random.default_rng(3)
    D, H = noise((nd, n), rng), noise((nt, n), rng)
    filt = mf.MatchedFilter(n, ndata=nd, ntemplates=nt)
    filt.set_data(D)
    filt.set_templates(H)
    full = filt.run(binsize=1024, threshold=0.0, window=(500, 3500))
    idx = full["index"]
    assert ((idx >= 500) & (idx < 3500)).all()
    sub = filt.run(binsize=1024, threshold=0.0, window=(500, 3500),
                 data=(1, 2), templates=(0, 2))
    np.testing.assert_array_equal(sub["index"], idx[1:3, 0:2])
    np.testing.assert_array_equal(sub["value"], full["value"][1:3, 0:2])


def test_raw_output_matches_structured():
    """raw=True must return exactly the structured array's contents."""
    n, nd, nt = 4096, 2, 3
    rng = np.random.default_rng(7)
    filt = mf.MatchedFilter(n, ndata=nd, ntemplates=nt)
    filt.set_data(noise((nd, n), rng))
    filt.set_templates(noise((nt, n), rng))
    peaks = filt.run(binsize=1024, threshold=0.0).copy()
    idx, val, mag = filt.run(binsize=1024, threshold=0.0, raw=True)
    np.testing.assert_array_equal(peaks["index"], idx)
    np.testing.assert_array_equal(peaks["value"], val)
    np.testing.assert_array_equal(peaks["magnitude"], mag)


def test_shape_errors():
    with pytest.raises(ValueError):
        mf.MatchedFilter(1000, 1, 1)          # not a supported length
    filt = mf.MatchedFilter(4096, ndata=1, ntemplates=1)
    with pytest.raises(ValueError):
        filt.set_data(np.zeros((1, 100), np.complex64))


# ------------------------------------------------- hierarchical filter

def test_hierarchical_is_identical_or_absent():
    """Reported peaks must be bit-identical; only omissions are allowed."""
    n, nd, nt = 4096, 4, 4
    rng = np.random.default_rng(11)
    power = inspiral_power(n)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    D = noise((nd, n), rng)
    for d in range(nd):                       # a loud signal so the gate fires
        lag = 300 + 17 * d
        D[d] += (12.0 * H[0] * np.exp(2j * np.pi * np.arange(n) * lag / n)
                 ).astype(np.complex64)

    filt = mf.MatchedFilter(n, ndata=nd, ntemplates=nt)
    hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=5.5, fd=1e-2)
    hf.set_reference(power)
    for o in (filt, hf):
        o.set_data(D)
        o.set_templates(H)
    a = filt.run(binsize=1024, threshold=5.5)
    b = hf.run(binsize=1024, threshold=5.5)

    fired = b["index"] >= 0
    assert fired.any(), "gate never opened on a 12-sigma signal"
    assert not (fired & (a["index"] < 0)).any(), "invented a peak"
    np.testing.assert_array_equal(a["index"][fired], b["index"][fired])
    np.testing.assert_array_equal(a["value"][fired], b["value"][fired])
    np.testing.assert_array_equal(a["magnitude"][fired], b["magnitude"][fired])


def test_gate_stays_shut_on_noise():
    n, nd = 4096, 64
    rng = np.random.default_rng(12)
    power = inspiral_power(n)
    hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=1, snr=5.5, fd=1e-2)
    hf.set_reference(power)
    hf.set_data(noise((nd, n), rng))
    hf.set_templates(template_with_power(n, power)[None, :])
    peaks = hf.run(binsize=n, threshold=5.5)
    assert (peaks["index"] < 0).all()
    assert hf.trigger_rate < 0.25


def test_omission_rate_meets_the_budget():
    """The false-dismissal budget is a promise; hold the code to it.

    Bit-identity says nothing about what is NOT reported, so without this a
    gate set too high passes every other test while quietly losing signals.
    """
    n, trials, snr, fd = 4096, 1500, 5.5, 1e-2
    rng = np.random.default_rng(13)
    power = inspiral_power(n)
    H = template_with_power(n, power)
    filt = mf.MatchedFilter(n, ndata=1, ntemplates=1)
    hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=1, snr=snr, fd=fd)
    hf.set_reference(power)
    filt.set_templates(H[None, :])
    hf.set_templates(H[None, :])

    detected = omitted = 0
    ph = np.exp(2j * np.pi * np.arange(n) / n)
    for i in range(trials):
        lag = (37 * i) % n
        D = noise((1, n), rng)
        D[0] += (snr * H * ph ** lag).astype(np.complex64)
        filt.set_data(D)
        hf.set_data(D)
        a = filt.run(binsize=n, threshold=snr)
        b = hf.run(binsize=n, threshold=snr)
        if a["index"][0, 0, 0] >= 0:
            detected += 1
            omitted += b["index"][0, 0, 0] < 0
    rate = omitted / max(detected, 1)
    # 3x absorbs binomial scatter at this trial count; beyond that the budget
    # is genuinely breached.
    assert rate <= 3 * fd, f"omitted {rate:.3%} of {detected}, budget {fd:.1%}"


def test_gate_reads_the_signal_not_the_template():
    """A broadband template whose output is narrowband -- the ratio-filter case.

    Without a reference the gate measures the template's own power and is badly
    wrong.  With one it measures the signal the template reconstructs.
    """
    n, band = 4096, 512
    rng = np.random.default_rng(14)
    rising = np.zeros(n, np.float32)
    k = np.arange(1, n // 2)
    rising[1:n // 2] = (k.astype(np.float64) ** 1.0).astype(np.float32)
    H = template_with_power(n, rising / rising.sum())      # power mostly HIGH
    data_power = np.zeros(n, np.float32)
    data_power[1:n // 2] = (k.astype(np.float64) ** -3.0).astype(np.float32)
    out_power = (np.abs(H) ** 2 * data_power).astype(np.float32)   # output LOW

    assert (np.abs(H[:band]) ** 2).sum() < 0.2          # template: high band
    assert out_power[:band].sum() / out_power.sum() > 0.9   # output: low band

    hf = mf.HierarchicalFilter(n, ndata=32, ntemplates=1, snr=5.5, fd=1e-2,
                                   band=band, oversample=2, taps=8)
    hf.set_reference(out_power)
    hf.set_templates(H[None, :])
    hf.set_data(noise((32, n), rng))
    hf.run(binsize=n, threshold=5.5)
    # Reading the template would both mis-scale the coarse series and mis-set
    # the gate; either way the gate fires on pure noise.
    assert hf.trigger_rate < 0.25


def test_coarse_scaling_follows_the_reference():
    """The 1/sqrt(f) scaling must use the reference's band fraction.

    It exists so the coarse series carries the same noise level as the full
    filter, which is what makes one threshold serve both.  Taking f from a
    broadband template whose output is narrowband inflates the coarse series --
    by 1/sqrt(0.06) = 4x here -- and the gate then fires on everything.
    """
    n, band = 4096, 512
    rng = np.random.default_rng(16)
    k = np.arange(1, n // 2)
    rising = np.zeros(n, np.float32)
    rising[1:n // 2] = (k.astype(np.float64) ** 1.0).astype(np.float32)
    H = template_with_power(n, rising / rising.sum())
    falling = np.zeros(n, np.float32)
    falling[1:n // 2] = (k.astype(np.float64) ** -3.0).astype(np.float32)
    out_power = (np.abs(H) ** 2 * falling).astype(np.float32)

    hf = mf.HierarchicalFilter(n, ndata=64, ntemplates=1, snr=5.5, fd=1e-2,
                                   band=band, oversample=2, taps=8)
    hf.set_reference(out_power)
    hf.set_templates(H[None, :])
    hf.set_data(noise((64, n), rng))
    hf.run(binsize=n, threshold=5.5)
    assert hf.trigger_rate < 0.25


def test_peaks_on_odd_lags_survive():
    """Regression: the even-grid recovery must span the even grid's spacing.

    Measured over offsets of R/U rather than R, graw1 came back 1.0 where the
    truth was 0.958, the even gate sat too high, and every peak landing on an
    odd lag was dismissed.  At band = n/2 that is R=2, so only odd lags expose
    it, and no other test here places a peak there.
    """
    n, band, snr = 4096, 2048, 6.0
    rng = np.random.default_rng(15)
    power = inspiral_power(n)
    H = template_with_power(n, power)
    filt = mf.MatchedFilter(n, ndata=1, ntemplates=1)
    hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=1, snr=snr, fd=1e-2,
                                   band=band, oversample=2, taps=8)
    hf.set_reference(power)
    filt.set_templates(H[None, :])
    hf.set_templates(H[None, :])
    ph = np.exp(2j * np.pi * np.arange(n) / n)
    detected = omitted = 0
    for i in range(200):
        lag = 2 * ((37 * i) % (n // 4)) + 1            # always ODD
        D = noise((1, n), rng)
        D[0] += ((snr + 0.6) * H * ph ** lag).astype(np.complex64)
        filt.set_data(D)
        hf.set_data(D)
        if filt.run(binsize=n, threshold=snr)["index"][0, 0, 0] >= 0:
            detected += 1
            omitted += hf.run(binsize=n, threshold=snr)["index"][0, 0, 0] < 0
    rate = omitted / max(detected, 1)
    assert rate <= 3e-2, f"dismissed {rate:.1%} of peaks on odd lags"


# -------------------------------------------- filtering a whole series

def overlap_save_layout(nseries, n, ntaps):
    """Block starts and per-block valid windows, as overlap-save produces them.

    Deliberately ragged at both ends, because that is the case that breaks a
    design taking one window for a whole call.
    """
    step = n - ntaps + 1
    starts, win_start, win_end = [], [], []
    for b in range((nseries - n) // step):
        starts.append(b * step)
        ws, we = ntaps // 2, ntaps // 2 + step
        if b == 0:
            ws = ntaps                       # ragged first
        if b == (nseries - n) // step - 1:
            we = ws + step // 2              # ragged last
        win_start.append(ws)
        win_end.append(we)
    return (np.array(starts, np.uintp), np.array(win_start, np.uintp),
            np.array(win_end, np.uintp))


def coloured_series(nseries, power_exponent, rng):
    """A long analytic series with a steeply falling spectrum."""
    x = noise(nseries, rng)
    f = np.arange(nseries)
    w = np.zeros(nseries)
    m = (f > 0) & (f < nseries // 2)
    w[m] = f[m].astype(np.float64) ** (power_exponent / 2.0)
    return np.fft.ifft(np.fft.fft(x) * w).astype(np.complex64)


def test_run_series_matches_block_by_block():
    """run_series must equal feeding the same blocks one at a time."""
    n, nseries, ntaps, nt = 4096, 1 << 16, 451, 4
    rng = np.random.default_rng(21)
    power = inspiral_power(n)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    ser = coloured_series(nseries, -7 / 3.0, rng)
    starts, ws, we = overlap_save_layout(nseries, n, ntaps)

    hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=nt, snr=5.0, fd=1e-2)
    hf.set_reference(power)
    hf.set_templates(H)
    got = hf.run_series(ser, starts, ws, we, binsize=n, threshold=0.0)

    for b, s in enumerate(starts):
        blk = np.zeros(n, np.complex64)
        seg = ser[s:s + n]
        blk[:len(seg)] = seg
        hf.set_data((np.fft.fft(blk) / n).astype(np.complex64)[None, :])
        want = hf.run(binsize=n, threshold=0.0,
                      window=(int(ws[b]), int(we[b])))
        np.testing.assert_array_equal(got["index"][b, :, 0], want["index"][0, :, 0])
        np.testing.assert_array_equal(got["value"][b, :, 0], want["value"][0, :, 0])


def test_bracket_does_not_change_what_is_reported():
    """The bracket settles pairs without the second coarse transform.

    It is allowed to do that only where the interpolated statistic's bracket
    does not straddle the gate, so every pair it settles it settles the way
    the transform would have.  Turning it off must therefore change the time
    taken and nothing else.  The reject side is the one that can cost a
    trigger if its margin is too tight, which is why this asserts identity
    rather than a tolerance -- a bracket that is merely close is a bracket
    that is silently dismissing signals.
    """
    n, nseries, ntaps, nt = 4096, 1 << 16, 451, 6
    rng = np.random.default_rng(11)
    power = inspiral_power(n)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    ser = coloured_series(nseries, -7 / 3.0, rng)
    starts, ws, we = overlap_save_layout(nseries, n, ntaps)

    def go(on):
        old = os.environ.get("MF_BRACKET")
        os.environ["MF_BRACKET"] = str(on)
        try:
            hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=nt, snr=5.0, fd=1e-2)
            hf.set_reference(power)
            hf.set_templates(H)
            r = hf.run_series(ser, starts, ws, we, binsize=n, threshold=0.0)
            return r["index"].copy(), r["value"].copy()
        finally:
            if old is None: del os.environ["MF_BRACKET"]
            else: os.environ["MF_BRACKET"] = old

    oi, ov = go(0)
    bi, bv = go(1)
    np.testing.assert_array_equal(bi, oi)
    np.testing.assert_array_equal(bv, ov)


def test_run_series_grouping_is_invisible():
    """How many blocks are filtered together must not change any output.

    run_series picks a data-batch size itself, because one segment against a
    large bank is the worst shape to hand the kernel.  That choice is a
    performance decision and nothing else: the grouped result has to be
    bit-identical to filtering one block at a time, including where a run of
    blocks is broken by the ragged windows at a segment's edges.
    """
    n, nseries, ntaps, nt = 4096, 1 << 16, 451, 6
    rng = np.random.default_rng(3)
    power = inspiral_power(n)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    ser = coloured_series(nseries, -7 / 3.0, rng)
    starts, ws, we = overlap_save_layout(nseries, n, ntaps)
    assert len(set(zip(map(int, ws), map(int, we)))) > 1, "need ragged windows"

    def go(group):
        old = os.environ.get("MF_DGROUP")
        os.environ["MF_DGROUP"] = str(group)
        try:
            hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=nt, snr=5.0, fd=1e-2)
            hf.set_reference(power)
            hf.set_templates(H)
            r = hf.run_series(ser, starts, ws, we, binsize=n, threshold=0.0)
            return r["index"].copy(), r["value"].copy()
        finally:
            if old is None: del os.environ["MF_DGROUP"]
            else: os.environ["MF_DGROUP"] = old

    bi, bv = go(1)
    for group in (2, 3, 8, 16):
        gi, gv = go(group)
        np.testing.assert_array_equal(gi, bi)
        np.testing.assert_array_equal(gv, bv)


@pytest.mark.xfail(
    reason="known: g and graw are measured from the reference's mean frequency "
           "series, "
           "which is not a bound on an individual realisation. Real peaks are "
           "sharper than the mean, so the gate sits too high and omits more "
           "than the budget allows -- ~5% here against 1%. graw1 was fixed this "
           "way already; g and graw were not. Reproduced independently in a "
           "418-template search: 1.4% against a 0.1% budget at snr 5.5. "
           "See docs/hierarchical.md.",
    strict=False)
def test_ratio_filter_shaped_workload():
    _ratio_filter_shaped_workload()


def _ratio_filter_shaped_workload():
    """The shape a ratio/FIR search actually uses.

    What makes it different from every other test here:
      * the templates are short, BROADBAND filters, while the SNR they
        reconstruct is strongly low-frequency -- so the gate has to read the
        reference, not the template;
      * the data is one long series walked by overlapping blocks;
      * each block carries its own window, ragged at the ends.

    The truth is the ungated filter on the same blocks.  Note this comparison
    is to a tolerance rather than bit-identical, unlike the other hierarchical
    tests: run_series does each block's forward transform inside matchedfilter while
    the reference path uses numpy's, and the two agree only to float32
    rounding.  Within a single path the guarantee is still exact.
    """
    n, nseries, ntaps, nt = 4096, 1 << 17, 451, 8
    rng = np.random.default_rng(22)
    ser = coloured_series(nseries, -7 / 3.0, rng)

    H = np.zeros((nt, n), np.complex64)          # broadband, analytic half
    for t in range(nt):
        k = np.arange(1, n // 2)
        amp = 0.5 + rng.uniform(0, 1, k.size)
        ph = rng.uniform(0, 2 * np.pi, k.size)
        H[t, 1:n // 2] = (amp * np.exp(1j * ph)).astype(np.complex64)
        H[t] /= np.linalg.norm(H[t])

    starts, ws, we = overlap_save_layout(nseries, n, ntaps)

    def block_spectrum(s):
        blk = np.zeros(n, np.complex64)
        seg = ser[s:s + n]
        blk[:len(seg)] = seg
        return (np.fft.fft(blk) / n).astype(np.complex64)

    # Scale so the OUTPUT has unit-variance components: that is what the
    # threshold is in.  Deriving this analytically is easy to get wrong -- the
    # series is coloured while |H|^2 is spread over every bin -- so measure it.
    probe = np.fft.ifft(block_spectrum(starts[0]) * np.conj(H[0])) * n
    ser *= np.float32(1.0 / probe.real.std())      # components, not |rho|

    # Reference: the series' own power on the block grid, as a caller measures
    # it.  Analytic, matching the half the kernel uses.
    ref = np.zeros(n, np.float64)
    for s in starts[:4]:
        ref += np.abs(block_spectrum(s)) ** 2
    ref[n // 2 + 1:] = 0
    ref = (ref / ref.sum()).astype(np.float32)

    # Inject signals rather than fishing for noise excursions.  The series is
    # heavily coloured, so the correlation is smooth over lags and carries far
    # fewer independent samples than its length suggests -- the noise maximum
    # sits near 3, not the sqrt(2 ln N) ~ 4 a white series would give.  Fishing
    # below that would leave the gate calibrated for one level and tested at
    # another; injecting keeps both at the same SNR.
    snr = 5.0
    ph = np.exp(2j * np.pi * np.arange(n) / n)
    # The injected signal has to have the same spectral shape as everything
    # else the gate sees.  Injecting H[t] itself gives a response proportional
    # to |H[t]|^2 -- broadband, since these filters are -- which the gate would
    # rightly dismiss as not looking like the reference.  Take the phase from
    # the template so the bins add coherently, and the amplitude from the
    # reference so the response lands where the gate is looking.
    amp = np.sqrt(ref).astype(np.complex64)
    unit = np.zeros(n, np.complex64)
    nz = np.abs(H[0]) > 0
    for b in range(len(starts)):
        for t in (b % nt, (b + 3) % nt):
            lag = int(ws[b]) + 101 * (b % 7) + 3 + 37 * t
            unit[:] = 0
            m = np.abs(H[t]) > 0
            unit[m] = H[t][m] / np.abs(H[t][m])
            inj = unit * amp * ph ** lag
            scale = (snr + 2.0) / max(np.abs(np.fft.ifft(inj * np.conj(H[t])) * n).max(), 1e-30)
            ser[starts[b]:starts[b] + n] += (np.fft.ifft(inj) * n * scale).astype(np.complex64)
    hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=nt, snr=snr, fd=1e-2,
                                   band=512, oversample=2, taps=8)
    hf.set_reference(ref)
    hf.set_templates(H)
    got = hf.run_series(ser, starts, ws, we, binsize=n, threshold=snr)

    filt = mf.MatchedFilter(n, ndata=1, ntemplates=nt)
    filt.set_templates(H)
    detected = omitted = invented = differ = 0
    for b, s in enumerate(starts):
        filt.set_data(block_spectrum(s)[None, :])
        want = filt.run(binsize=n, threshold=snr,
                      window=(int(ws[b]), int(we[b])))[0, :, 0]
        have = got[b, :, 0]
        for t in range(nt):
            if want["index"][t] >= 0:
                detected += 1
                if have["index"][t] < 0:
                    omitted += 1
                elif (have["index"][t] != want["index"][t]
                      or abs(have["magnitude"][t] - want["magnitude"][t])
                      > 1e-4 * want["magnitude"][t]):
                    differ += 1
            elif have["index"][t] >= 0:
                invented += 1

    assert detected > 50, f"only {detected} peaks; the test is not exercising the gate"
    assert invented == 0, f"invented {invented} peaks"
    assert differ == 0, f"{differ} recovered peaks differ from the ungated filter"
    assert omitted / detected <= 3e-2, f"omitted {omitted}/{detected}"


def test_autotuned_calibration_meets_the_budget_where_the_default_does_not():
    """`MF_GCAL=1` is what makes the false-dismissal budget hold.

    `test_ratio_filter_shaped_workload` above is xfail for exactly one reason:
    g and graw are derived from a noiseless autocorrelation of the reference's
    MEAN spectrum, which is not a bound on any individual realisation, so the
    gate sits too high and the omission rate runs ~5% against a 1% budget.
    The autotune re-measures both over realisations and the budget then holds.

    Pinning that here does two things. It stops the autotune silently ceasing
    to work -- nothing else in the suite exercises it. And it makes the xfail
    above a statement about the DEFAULT rather than about the method: the
    calibration is capable of meeting the budget, it is simply not on, because
    it also over-corrects and costs ~9% more than tuning the gate by hand
    (14.43 against 13.29 ms/segment on the captures, both at zero loss).
    """
    old = os.environ.get("MF_GCAL")
    os.environ["MF_GCAL"] = "1"
    try:
        _ratio_filter_shaped_workload()
    finally:
        if old is None: del os.environ["MF_GCAL"]
        else: os.environ["MF_GCAL"] = old


def test_band_autoselect_is_off_and_the_default_band_is_used():
    """The power-driven band choice must stay off until it can decide.

    `select_band` probes every candidate band against the caller's reference
    and rebuilds the plan around the cheapest. The mechanism works; the
    decision does not, because the gate is calibrated on the SIGNAL's band
    fraction while the coarse statistic's noise comes from the FILTER's, and
    those diverge (0.9335 against 0.4517 at band 512 on the captures). Driven
    by the reference alone it picks too narrow and loses triggers -- 110 of
    842 against 31.

    So this asserts the default is untouched by a reference, and that the
    machinery is still reachable behind the flag. When the missing term lands,
    this test is what says the default has changed.
    """
    n, nt = 4096, 4
    power = inspiral_power(n)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])

    def band_after_reference(env):
        old = os.environ.get("MF_AUTOBAND")
        if env is None: os.environ.pop("MF_AUTOBAND", None)
        else: os.environ["MF_AUTOBAND"] = env
        try:
            hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=nt, snr=5.0, fd=1e-3)
            before = hf.config[0]
            hf.set_reference(power)
            hf.set_templates(H)
            return before, hf.config[0]
        finally:
            if old is None: os.environ.pop("MF_AUTOBAND", None)
            else: os.environ["MF_AUTOBAND"] = old

    before, after = band_after_reference(None)
    assert after == before, (
        f"set_reference changed the band {before} -> {after} with the "
        "autoselect off; it must not")
    _, picked = band_after_reference("1")
    assert picked > 0


def test_python_overhead_stays_off_the_hot_path():
    """The whole D x T pair loop is one call into C, so per-pair cost must not
    scale with how much Python ran.

    Compare one pair against the amortised cost of 64.  If the glue dominated,
    the single pair would carry the entire call overhead and the ratio would
    blow up.  The bound is deliberately loose -- this is guarding against a
    structural regression (per-pair Python work creeping back in), not
    measuring anything, and it has to survive a noisy shared CI runner.
    """
    n, nd, nt = 4096, 8, 8
    rng = np.random.default_rng(13)
    h = template_with_power(n, inspiral_power(n))
    filt = mf.MatchedFilter(n, nd, nt)
    filt.set_data(noise((nd, n), rng))
    filt.set_templates(np.repeat(h[None, :], nt, axis=0))

    one = all_pairs = float("inf")
    for _ in range(5):
        t0 = time.perf_counter()
        filt.run(binsize=1024, data=(0, 1), templates=(0, 1))
        one = min(one, time.perf_counter() - t0)
        t0 = time.perf_counter()
        filt.run(binsize=1024)
        all_pairs = min(all_pairs, time.perf_counter() - t0)

    per_pair = all_pairs / (nd * nt)
    assert one < 40 * per_pair, (
        "one pair costs %.1f us against %.1f us amortised; Python overhead is "
        "back on the per-pair path" % (one * 1e6, per_pair * 1e6))


def test_first_stage_threshold_is_independent_of_configuration():
    """set_first_stage moves the first-stage level, nothing else.

    The value derived from (snr, fd) comes from an offline sweep whose
    recovery factors are measured against a mean spectrum, and it is wrong in
    at least one cell -- see docs/hierarchical.md.  So a caller has to be able
    to override it, and two properties have to hold: lowering it makes the
    first stage strictly more willing to reconstruct (unlike passing a
    different snr at construction, which selects a whole new configuration),
    and it leaves band/oversample/taps alone.

    Signals are injected deliberately.  On pure noise at this threshold the
    first stage never fires at any level, every rate is zero, and a
    monotonicity assertion over constants passes whatever the code does --
    which is exactly what an earlier version of this test did.
    """
    n, nd, nt = 4096, 64, 8
    rng = np.random.default_rng(3)
    power = inspiral_power(n)
    h = np.repeat(template_with_power(n, power)[None, :], nt, axis=0)
    d = noise((nd, n), rng)
    for i in range(0, nd, 4):
        d[i] += (6.0 * np.fft.fft(np.roll(np.fft.ifft(h[i % nt]), i * 37))
                 ).astype(np.complex64)

    rates, cfgs = {}, {}
    for fs in (None, 6.0, 5.5, 5.0):
        hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=5.5,
                                   fd=1e-3, band=512, oversample=2, taps=8)
        hf.set_reference(power)
        hf.set_templates(h)
        hf.set_data(d)
        hf.set_first_stage(fs)
        hf.run(binsize=n, threshold=5.5)
        rates[fs], cfgs[fs] = hf.trigger_rate, hf.config

    # the workload must actually exercise the first stage, or the rest is vacuous
    assert rates[5.5] > 0.01, (
        "first stage never fires, so this test proves nothing: " + repr(rates))

    assert len(set(cfgs.values())) == 1, "configuration moved: %r" % (cfgs,)

    # explicitly setting the derived value must reproduce it
    assert rates[5.5] == pytest.approx(rates[None], rel=1e-6)

    # and lowering it can only reconstruct more often
    ordered = [rates[6.0], rates[5.5], rates[5.0]]
    assert ordered == sorted(ordered), (
        "rate must rise as the first-stage SNR falls, got " + repr(rates))


def test_first_stage_below_the_design_grid_is_clamped():
    """Values under the design table's lowest SNR saturate rather than scale.

    hmf_threshold clamps its snr argument to the table's grid, whose floor is
    4.5, so asking for less is silently the same as asking for 4.5.  Worth a
    test because the call succeeds and looks like it did something.
    """
    n, nd, nt = 4096, 64, 8
    rng = np.random.default_rng(3)
    power = inspiral_power(n)
    h = np.repeat(template_with_power(n, power)[None, :], nt, axis=0)
    d = noise((nd, n), rng)
    for i in range(0, nd, 4):
        d[i] += (6.0 * np.fft.fft(np.roll(np.fft.ifft(h[i % nt]), i * 37))
                 ).astype(np.complex64)

    got = {}
    for fs in (4.5, 3.0, 0.01):
        hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=5.5,
                                   fd=1e-3, band=512, oversample=2, taps=8)
        hf.set_reference(power)
        hf.set_templates(h)
        hf.set_data(d)
        hf.set_first_stage(fs)
        hf.run(binsize=n, threshold=5.5)
        got[fs] = hf.trigger_rate
    assert got[3.0] == pytest.approx(got[4.5], rel=1e-6)
    assert got[0.01] == pytest.approx(got[4.5], rel=1e-6)
