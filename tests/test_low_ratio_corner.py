"""The threshold table's low-ratio corner is optimistic, and that is why
bands 64 and 128 are supported but not selectable.

docs/tooling-cleanup.md recorded the blocker as a *performance* regression:
installing the measured small-band cost rows made selection pick band 128/K4
at 4.37x where band 512/K4 measured 10.75x. That is a symptom. The reason
band 128 looked cheap and was not worth taking is that it should not have
been admissible at all -- at the reference it was picked for it dismisses
2.9e-2 of INJECTED SIGNALS against a 1e-3 budget.

What is actually wrong is narrower than "small bands are bad", and the
measurements below are what bound it:

    band   f       ratio   table thr   injections dismissed
     128   0.6970   1.24      3.3341    15 of 523 = 2.9e-2   <-- over
     128   0.9476   2.68      3.9209     0 of 533
     128   0.9858   6.60      4.3348     1 of 550
     128   0.9939  12.18      4.1129     0 of 556
     256   0.8832   1.66      3.5307     0 of 523
     256   0.9801   5.01      4.1300     1 of 533

Band 128 is fine everywhere except the low-ratio corner, and band 256 is
fine AT 1.66. Dropping the band-128 threshold 10%, to 3.0007, takes the
dismissal to 0 of 605 -- so the table row is about 11% too high rather than
the configuration being unusable.

`ratio` is samples across the correlation peak, band / B_eff, and the table
is keyed on it precisely because band is supposed to drop out. Near the grid
edge it does not: the table's ratio grid starts at 1.200, the failing query
sits at 1.24, and the same table serves a query at 1.37 (f = 0.695, band
1024) that passes. Whatever the cause -- a steep gradient the bilinear fit
misses, or rows at ratio 1.20 measured at 6000 trials against a 1e-3 budget
they cannot resolve -- the fix is measured rows below ratio 1.5 with enough
trials, not a constant subtracted here.

Selection cannot reach the failing corner today: the lowest ratio it picks
over 352 sampled (n, reference, snr, fd) combinations is 1.29, at f = 0.787,
and that measures 0 of 598. Installing the small-band cost rows is what
makes it reachable. So this test stands between those rows and the default
path, and it is deliberately written to FAIL if someone installs them
without fixing the table first.
"""
import numpy as np
import pytest

import matchedfilter as mf
from test_api import inspiral_power, template_with_power, noise


N = 4096
SNR = 5.0
FD = 1e-3


def _dismissal(power, band, reps=12, nb=64, nt=16, thr=None):
    H = np.stack([template_with_power(N, power) for _ in range(nt)])
    flat = mf.MatchedFilter(N, nb, nt)
    flat.set_templates(H)
    hier = mf.HierarchicalFilter(N, nb, nt, snr=SNR, fd=FD, band=band, taps=8)
    hier.set_reference(power)
    hier.set_templates(H)
    if thr is not None:
        hier.set_coarse_threshold(thr)
    ph = np.exp(2j * np.pi * np.arange(N) / N)
    rng = np.random.default_rng(23)
    detected = omitted = 0
    for _ in range(reps):
        D = noise((nb, N), rng)
        which = rng.integers(0, nt, nb)
        for b in range(nb):
            lag = int(rng.integers(0, N))
            D[b] += (1.04 * SNR * H[which[b]] * ph ** lag).astype(np.complex64)
        flat.set_data(D)
        hier.set_data(D)
        a = flat.run(binsize=N, threshold=SNR)
        c = hier.run(binsize=N, threshold=SNR)
        for b in range(nb):
            t = which[b]
            if a["index"][b, t, 0] >= 0:
                detected += 1
                omitted += int(c["index"][b, t, 0] < 0)
    return detected, omitted


def test_the_low_ratio_corner_still_misses_its_budget():
    """Pins the defect, so enabling small bands cannot quietly ship it.

    Asserted in the direction it actually fails. If the threshold table is
    re-measured at low ratio and this starts passing, that is the fix
    landing -- delete the test and enable the bands, do not relax it.
    """
    power = inspiral_power(N)
    f, be = mf._band_features(power, 128)
    assert 1.20 < 128 / be < 1.35, \
        "this reference no longer lands in the corner under test: ratio %.2f" \
        % (128 / be)
    detected, omitted = _dismissal(power, 128)
    assert detected > 300, "too few detections to say anything: %d" % detected
    rate = omitted / detected
    assert rate > 10 * FD, (
        "band 128 at ratio %.2f now dismisses %.2e, within reach of the %.0e "
        "budget. If the threshold table was re-measured at low ratio, this "
        "test has served its purpose: delete it and install the small-band "
        "cost rows (tools/cost-small-bands-4096-experimental.txt)."
        % (128 / be, rate, FD))


def test_band_128_is_sound_away_from_the_corner():
    """The defect is the corner, not the band.

    Without this the obvious reading of the test above is "band 128 does
    not work", and the obvious response is to drop the pair-batched small
    sizes that were built to support it.
    """
    power = inspiral_power(N, knee_frac=0.004)
    f, be = mf._band_features(power, 128)
    assert 128 / be > 2.0, "expected a comfortable ratio, got %.2f" % (128 / be)
    detected, omitted = _dismissal(power, 128)
    assert detected > 300, "too few detections to say anything: %d" % detected
    rate = omitted / detected
    assert rate <= FD * 10, \
        "band 128 dismissed %d of %d at ratio %.2f, %.2e" \
        % (omitted, detected, 128 / be, rate)


def test_selection_does_not_reach_the_corner_today():
    """The reason the defect is latent rather than live.

    Sampled over n, reference shape, snr and fd. If a change to selection
    or to the tables lets it pick a lower ratio, this fails BEFORE a user
    meets a gate that misses its budget.
    """
    worst = None
    for n in (2048, 4096, 16384):
        for exponent in (-7 / 3.0, -2.0, -5 / 3.0):
            for knee in (0.0150, 0.05, 0.002):
                power = inspiral_power(n, exponent=exponent, knee_frac=knee)
                for snr in (5.0, 5.5, 6.0, 6.5):
                    for fd in (1e-2, 1e-3):
                        try:
                            cfg = mf.choose_config(power, n, snr, fd)
                        except Exception:
                            continue
                        if not cfg:
                            continue
                        _f, be = mf._band_features(power, cfg[0])
                        if be <= 0:
                            continue
                        r = cfg[0] / be
                        if worst is None or r < worst[0]:
                            worst = (r, n, snr, fd, cfg[0])
    assert worst is not None, "selection returned nothing anywhere"
    assert worst[0] >= 1.25, (
        "selection now picks ratio %.2f (n=%d snr=%.1f fd=%.0e band=%d). "
        "Measured, ratio 1.24 dismisses 2.9e-2 against a 1e-3 budget; the "
        "lowest ratio previously reachable was 1.29." % worst)
