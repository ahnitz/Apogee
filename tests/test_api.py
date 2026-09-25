"""Tests for matchedfilter's public API.

Everything reachable from Python lives here.  The one exception is
tests/test_units.c, which checks the generated codelets, the transpose and the
int16 kernels directly -- those are internal and there is no way to reach them
through MatchedFilter or HierarchicalFilter.

The hierarchical tests are written around a single idea: the guarantee is
one-sided.  A reported peak must be bit-identical to the full filter's,
because when the coarse pass escalates it runs that filter.  Only omissions are allowed,
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

def inspiral_power(n, exponent=-7 / 3.0, knee_frac=0.0150):
    """|h|^2/S for an inspiral-like signal: steeply falling, one-sided.

    The low-frequency knee is not decoration. Without it a raw f^(-7/3)
    curve puts half its power in bin 1, giving an effective bandwidth of
    1.9 bins against 141 for a real captured reference -- and at B_eff
    near 1 the correlation magnitude is nearly CONSTANT in lag, so there
    is no peak to find coarsely and refine. The library now refuses such
    a reference rather than pretending to tune for it.

    matchedfilter.benchmark._inspiral_power had exactly this bug and its
    docstring records the fix; this helper never got it.
    """
    p = np.zeros(n, dtype=np.float32)
    k = np.arange(1, n // 2).astype(np.float64)
    p[1:n // 2] = (k ** exponent / ((knee_frac * n / k) ** 4 + 1.0)
                   ).astype(np.float32)
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
    idx, val = filt.run(binsize=1024, threshold=0.0, raw=True)
    np.testing.assert_array_equal(peaks["index"], idx)
    np.testing.assert_array_equal(peaks["value"], val)


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
    for d in range(nd):                       # a loud signal so the coarse pass escalates
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
    assert fired.any(), "margin never opened on a 12-sigma signal"
    assert not (fired & (a["index"] < 0)).any(), "invented a peak"
    np.testing.assert_array_equal(a["index"][fired], b["index"][fired])
    np.testing.assert_array_equal(a["value"][fired], b["value"][fired])
    np.testing.assert_array_equal(np.abs(a["value"])[fired], np.abs(b["value"])[fired])


def test_coarse_pass_rules_out_pure_noise():
    n, nd = 4096, 64
    rng = np.random.default_rng(12)
    power = inspiral_power(n)
    hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=1, snr=5.5, fd=1e-2)
    hf.set_reference(power)
    hf.set_data(noise((nd, n), rng))
    hf.set_templates(template_with_power(n, power)[None, :])
    peaks = hf.run(binsize=n, threshold=5.5)
    assert (peaks["index"] < 0).all()
    assert hf.refine_rate < 0.25


def test_omission_rate_meets_the_budget():
    """The false-dismissal budget is a promise; hold the code to it.

    Bit-identity says nothing about what is NOT reported, so without this a
    margin set too high passes every other test while quietly losing signals.
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


def test_coarse_threshold_reads_the_reference_not_the_template():
    """A broadband template whose output is narrowband -- the ratio-filter case.

    Without a reference the coarse threshold measures the template's own power and is badly
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
                                   band=band, taps=8)
    hf.set_reference(out_power)
    hf.set_templates(H[None, :])
    hf.set_data(noise((32, n), rng))
    hf.run(binsize=n, threshold=5.5)
    # Reading the template would both mis-scale the coarse series and mis-set
    # the coarse threshold; either way the coarse pass escalates on pure noise.
    assert hf.refine_rate < 0.25


def test_coarse_scaling_follows_the_reference():
    """The 1/sqrt(f) scaling must use the reference's band fraction.

    It exists so the coarse series carries the same noise level as the full
    filter, which is what makes one threshold serve both.  Taking f from a
    broadband template whose output is narrowband inflates the coarse series --
    by 1/sqrt(0.06) = 4x here -- and the coarse threshold then fires on everything.
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
                                   band=band, taps=8)
    hf.set_reference(out_power)
    hf.set_templates(H[None, :])
    hf.set_data(noise((64, n), rng))
    hf.run(binsize=n, threshold=5.5)
    assert hf.refine_rate < 0.25


def test_peaks_on_odd_lags_survive():
    """Regression: the even-grid recovery must span the even grid's spacing.

    Measured over offsets of R/U rather than R, graw1 came back 1.0 where the
    truth was 0.958, the even-pass threshold sat too high, and every peak landing on an
    odd lag was dismissed.  At band = n/2 that is R=2, so only odd lags expose
    it, and no other test here places a peak there.
    """
    n, band, snr = 4096, 2048, 6.0
    rng = np.random.default_rng(15)
    power = inspiral_power(n)
    H = template_with_power(n, power)
    filt = mf.MatchedFilter(n, ndata=1, ntemplates=1)
    hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=1, snr=snr, fd=1e-2,
                                   band=band, taps=8)
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


def coloured_series(nseries, power_exponent, rng, knee_frac=0.0150):
    """A long analytic series with a steeply falling spectrum.

    `knee_frac` is the low-frequency cutoff, as a fraction of the block
    length the search will use. Every real instrument has one -- it is the
    seismic wall -- and without it a -7/3 series piles 99.5% of its power
    into bins 0-3. The reference derived from such a series has an
    effective bandwidth near 1, where the correlation magnitude is nearly
    constant in lag and the hierarchical method has no peak to localise.
    """
    x = noise(nseries, rng)
    f = np.arange(nseries)
    w = np.zeros(nseries)
    m = (f > 0) & (f < nseries // 2)
    w[m] = f[m].astype(np.float64) ** (power_exponent / 2.0)
    if knee_frac > 0:
        # the knee is quoted against the BLOCK length, so scale it to the
        # series; both refer to the same physical frequency
        knee = knee_frac * nseries
        w[m] /= ((knee / f[m].astype(np.float64)) ** 4 + 1.0) ** 0.5
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
        # int(), because starts is uintp and NumPy 1 promotes
        # uint64 + Python int to FLOAT64 -- which is not a valid slice index.
        # NumPy 2's NEP 50 keeps it integral, so this passes there and fails
        # on the floor the package actually claims (numpy>=1.20).
        seg = ser[int(s):int(s) + n]
        blk[:len(seg)] = seg
        hf.set_data((np.fft.fft(blk) / n).astype(np.complex64)[None, :])
        want = hf.run(binsize=n, threshold=0.0,
                      window=(int(ws[b]), int(we[b])))
        np.testing.assert_array_equal(got["index"][b, :, 0], want["index"][0, :, 0])
        np.testing.assert_array_equal(got["value"][b, :, 0], want["value"][0, :, 0])


def test_bracket_does_not_change_what_is_reported():
    """The bracket settles pairs without the second coarse transform.

    It is allowed to do that only where the interpolated statistic's bracket
    does not straddle the coarse threshold, so every pair it settles it settles the way
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


def test_ratio_filter_shaped_workload():
    """The pinned path meets the budget too, now that it reads the table.

    This was xfail for a long time, and correctly: pinning band/taps skipped
    selection, which is also where the coarse margin was resolved, so the
    threshold came wholly from the compiled model in src/hmf_table.h.  That
    model's recovery factors are measured from the reference's MEAN spectrum
    and are not a bound on any single realisation -- real peaks are sharper,
    the threshold sat too high, and this omitted 8 of 140 against a 3%
    budget.  Pinning now takes the margin from the same measured rows
    selection would have used; here that is 0.97, and nothing is lost.
    """
    _ratio_filter_shaped_workload(pin=True)


def test_pinning_reads_the_margin_from_the_table():
    """Pinning bypasses the CHOICE, not the evidence.

    The regression this guards is silent in every other test: an implicit
    1.00 still runs, still reports peaks, and only drops the marginal ones.
    """
    n = 4096
    k = np.arange(1, n // 2)
    power = np.zeros(n, np.float32)
    power[1:n // 2] = k ** (-7 / 3.0) / ((0.015 * n / k) ** 4 + 1.0)
    power /= power.sum()

    # A tighter budget must never give a LOOSER threshold. Not strictly
    # tighter: where the whole margin curve sits near the table's
    # resolution floor, the loosest setting already meets several budgets
    # and the right answer is the same margin for each. At 24000 trials
    # this cell reads 1.25e-4 flat to margin 0.98 and 9.35e-4 at 1.00, so
    # 1e-2 and 1e-3 both admit 1.00 and only 1e-4 forces 0.90.
    ms = [mf.margin_for_config(power, n, 5.0, fd, 512, 8)
          for fd in (1e-2, 1e-3, 1e-4)]
    assert all(m is not None and 0.5 < m <= 1.0 for m in ms), ms
    assert ms[0] >= ms[1] >= ms[2], ms
    assert ms[2] < ms[0], ms            # somewhere in the range it must bite

    # below what the table resolves it saturates at the tightest measured
    # margin rather than falling back to 1.00, which would hand the
    # strictest budget the loosest threshold
    assert mf.margin_for_config(power, n, 5.0, 1e-9, 512, 8) == \
        pytest.approx(0.90)

    # band is not in the key any more, so an off-grid band is perfectly
    # answerable -- it enters only through the (f, B_eff) at its own edge
    assert mf.margin_for_config(power, n, 5.0, 1e-3, 333, 8) is not None

    # what is NOT answerable is a reference with no localised peak: all its
    # power in a bin or two means the correlation is flat in lag
    flat = np.zeros(n, np.float32); flat[3] = 1.0
    assert mf.margin_for_config(flat, n, 5.0, 1e-3, 512, 8) is None

    # and the plan actually applies it
    want = mf.margin_for_config(power, n, 5.0, 1e-3, 512, 8)
    hf = mf.HierarchicalFilter(n, 1, 2, snr=5.0, fd=1e-3,
                               band=512, taps=8)
    hf.set_reference(power)
    hf._ensure()
    assert hf._margin == pytest.approx(want)


def test_an_explicit_margin_beats_the_table_on_a_pinned_plan():
    """set_coarse_margin after set_reference must win, including at 1.0.

    The table margin is applied as the reference arrives, precisely so it
    lands BEFORE anything the caller does. Resolving it at first run instead
    put it after, which silently overwrote an explicit setting -- and the
    cost tuner sweeps the margin as an independent variable, skipping the
    call when it wants 1.0, so every 1.0 cell of a regenerated table would
    have been measured at the table's margin rather than at 1.0.
    """
    n = 4096
    k = np.arange(1, n // 2)
    power = np.zeros(n, np.float32)
    power[1:n // 2] = k ** (-7 / 3.0) / ((0.015 * n / k) ** 4 + 1.0)
    power /= power.sum()

    auto = mf.margin_for_config(power, n, 5.0, 1e-3, 512, 8)
    assert auto is not None, auto
    if abs(auto - 1.0) <= 1e-2:
        # the table says this cell is safe even wide open; compare the two
        # explicit settings instead, which is the property being guarded
        auto = None

    rng = np.random.default_rng(5)
    h = template_with_power(n, power)
    h = np.repeat(h[None, :], 4, axis=0)
    d = noise((8, n), rng)
    for i in range(0, 8, 2):
        d[i] += (6.0 * np.fft.fft(np.roll(np.fft.ifft(h[0]), i * 53))
                 ).astype(np.complex64)

    rates = {}
    for explicit in (None, 1.0, 0.90):
        hf = mf.HierarchicalFilter(n, 8, 4, snr=5.0, fd=1e-3,
                                   band=512, taps=8)
        hf.set_reference(power)
        if explicit is not None:
            hf._mf.set_coarse_margin(explicit)
        hf.set_templates(h)
        hf.set_data(d)
        hf.run(binsize=n, threshold=5.0)
        rates[explicit] = hf.refine_rate

    # 1.0 is the loosest coarse threshold, so it must escalate no more than
    # any tighter one, and 0.90 must escalate more. That is the property:
    # an explicit setting reaches the plan and moves it in the right
    # direction.
    assert rates[0.90] > rates[1.0], rates
    assert rates[1.0] <= rates[None] + 1e-9, rates


def test_autotuned_selection_meets_the_budget_where_a_pinned_band_does_not():
    """The same workload, with the library choosing instead of the caller.

    This is the whole claim of the tuning tables in one assertion: given only
    the reference and the budget, selection finds a configuration that meets
    the budget on a workload where a hand-picked band does not.
    `test_ratio_filter_shaped_workload` above is the pinned half of the pair.
    It was xfail until pinning learned to read the same measured rows; both
    halves now pass, and they pass for the same reason, which is the point.
    If either starts failing the tables have gone stale against the code and
    regenerating them is the fix, not loosening the bound.
    """
    _ratio_filter_shaped_workload(pin=False)

def _ratio_filter_shaped_workload(pin=True):
    """The shape a ratio/FIR search actually uses.

    What makes it different from every other test here:
      * the templates are short, BROADBAND filters, while the SNR they
        reconstruct is strongly low-frequency -- so the coarse threshold has to read the
        reference, not the template;
      * the data is one long series walked by overlapping blocks;
      * each block carries its own window, ragged at the ends.

    The truth is the full filter on the same blocks.  Note this comparison
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
        # int(), because starts is uintp and NumPy 1 promotes
        # uint64 + Python int to FLOAT64 -- which is not a valid slice index.
        # NumPy 2's NEP 50 keeps it integral, so this passes there and fails
        # on the floor the package actually claims (numpy>=1.20).
        seg = ser[int(s):int(s) + n]
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
    # below that would leave the coarse threshold calibrated for one level and tested at
    # another; injecting keeps both at the same SNR.
    snr = 5.0
    ph = np.exp(2j * np.pi * np.arange(n) / n)
    # The injected signal has to have the same spectral shape as everything
    # else the coarse threshold sees.  Injecting H[t] itself gives a response proportional
    # to |H[t]|^2 -- broadband, since these filters are -- which the coarse threshold would
    # rightly dismiss as not looking like the reference.  Take the phase from
    # the template so the bins add coherently, and the amplitude from the
    # reference so the response lands where the coarse threshold is looking.
    # Amplitude chosen so the RESPONSE is ifft(ref), which is what a real
    # signal produces: matched filtering h against h gives |h|^2/S, i.e.
    # the reference itself. The earlier sqrt(ref) made the response
    # ifft(sqrt(ref)*|H|), broader in frequency and so a NARROWER peak in
    # lag than the reference describes -- it exercised a scalloping regime
    # the coarse threshold was never told about, and lost 29% where the
    # same configuration on the same reference measures 1.3e-3.
    amp = ref.astype(np.float64)
    unit = np.zeros(n, np.complex64)
    nz = np.abs(H[0]) > 0
    for b in range(len(starts)):
        for t in (b % nt, (b + 3) % nt):
            lag = int(ws[b]) + 101 * (b % 7) + 3 + 37 * t
            unit[:] = 0
            m = np.abs(H[t]) > 0
            # inj * conj(H) = ref, so the response is ifft(ref)
            unit[m] = H[t][m] / (np.abs(H[t][m]) ** 2)
            inj = (unit * amp * ph ** lag).astype(np.complex64)
            scale = (snr + 2.0) / max(np.abs(np.fft.ifft(inj * np.conj(H[t])) * n).max(), 1e-30)
            s0 = int(starts[b])          # uintp; see the note above
            ser[s0:s0 + n] += (np.fft.ifft(inj) * n * scale).astype(np.complex64)
    hf = (mf.HierarchicalFilter(n, ndata=1, ntemplates=nt, snr=snr, fd=1e-2,
                                band=512, taps=8) if pin else
          mf.HierarchicalFilter(n, ndata=1, ntemplates=nt, snr=snr, fd=1e-2))
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
                      or abs(np.abs(have["value"])[t] - np.abs(want["value"])[t])
                      > 1e-4 * np.abs(want["value"])[t]):
                    differ += 1
            elif have["index"][t] >= 0:
                invented += 1

    assert detected > 50, f"only {detected} peaks; the test is not exercising the coarse threshold"
    assert invented == 0, f"invented {invented} peaks"
    assert differ == 0, f"{differ} recovered peaks differ from the full filter"
    assert omitted / detected <= 3e-2, f"omitted {omitted}/{detected}"


def test_autotuned_calibration_meets_the_budget_where_the_default_does_not():
    """`MF_GCAL=1` is what makes the false-dismissal budget hold.

    g and graw are derived from a noiseless autocorrelation of the
    reference's MEAN spectrum, which is not a bound on any individual
    realisation, so the modelled threshold sits too high.  That is what made
    `test_ratio_filter_shaped_workload` above xfail while the pinned path had
    nothing but the model: 8 of 140 omitted against a 3% budget.  This
    calibration re-measures both over realisations and the budget then holds.

    The measured margin now fixes the same workload more cheaply, so this is
    no longer the only route to it -- but the calibration is still the only
    thing that helps where the tables have no row, and nothing else in the
    suite exercises it, so it is pinned here to stop it rotting.  It is off
    by default because it over-corrects: ~9% more than tuning the coarse
    threshold by hand, 14.43 against 13.29 ms/segment on the captures, both
    at zero loss.
    """
    old = os.environ.get("MF_GCAL")
    os.environ["MF_GCAL"] = "1"
    try:
        _ratio_filter_shaped_workload()
    finally:
        if old is None: del os.environ["MF_GCAL"]
        else: os.environ["MF_GCAL"] = old


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
    and it leaves band/taps alone.

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
                                   fd=1e-3, band=512, taps=8)
        hf.set_reference(power)
        hf.set_templates(h)
        hf.set_data(d)
        hf.set_first_stage(fs)
        hf.run(binsize=n, threshold=5.5)
        rates[fs], cfgs[fs] = hf.refine_rate, hf.config

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
                                   fd=1e-3, band=512, taps=8)
        hf.set_reference(power)
        hf.set_templates(h)
        hf.set_data(d)
        hf.set_first_stage(fs)
        hf.run(binsize=n, threshold=5.5)
        got[fs] = hf.refine_rate
    assert got[3.0] == pytest.approx(got[4.5], rel=1e-6)
    assert got[0.01] == pytest.approx(got[4.5], rel=1e-6)


@pytest.mark.parametrize("klass", ["flat", "hier"])
def test_run_without_set_data_raises_rather_than_crashing(klass):
    """run() with no data must be an error, not a segmentation fault.

    ap_hmf_set_data stores the CALLER'S spectrum pointer, and the refine path
    is the first thing to dereference it. With no set_data() that pointer was
    NULL, so run() segfaulted -- but only once a pair actually fired, which
    made it look intermittent rather than like a missing call. It took gdb to
    see that the crash was in ap_mf_set_data called from ap_hmf_run, and a
    printf to see that the spectrum it was handed was nil.

    The flat filter never crashed here; it read its zeroed buffers and
    returned zeros, which is its own kind of wrong. Both refuse now.
    """
    n, nt = 1024, 4
    power = inspiral_power(n)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    if klass == "flat":
        f = mf.MatchedFilter(n, 1, nt)
    else:
        f = mf.HierarchicalFilter(n, 1, nt, snr=5.5, fd=1e-2, band=256,
                                  taps=8)
        f.set_reference(power)
    f.set_templates(H)
    with pytest.raises(ValueError, match="set_data"):
        f.run(binsize=n, threshold=5.5)
