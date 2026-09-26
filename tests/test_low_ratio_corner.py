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

Bisecting the table against measurement (tools/audit_threshold.py) says the
error is not one bad cell but a GRADIENT, present wherever the ratio is
small and growing as it falls:

    band   f       ratio   measured safe   table    table is
     128   0.6970   1.24       2.8956      3.3341   15.1% HIGH
     256   0.8832   1.66       3.3843      3.5307    4.3% high
     512   0.9584   2.83       3.8774      4.0354    4.1% high
    1024   0.9882   5.33       4.3502      4.2423    2.5% low

A threshold above the safe value dismisses signals, so "high" is the unsafe
direction. At ratio 5 and up the table is correct or conservative. Below it
the rows are a few percent optimistic -- bands 256 and 512, which selection
ships, are running 4% hot and pass only because they have slack -- and by
ratio 1.24 the error reaches 15% and breaks through.

`ratio` is samples across the correlation peak, band / B_eff, and the table
is keyed on it precisely because band is supposed to drop out. The rows
themselves barely move with it: at f = 0.5000 the measured thresholds run
3.2441, 3.2500, 3.2148, 3.2383 across ratio 1.2 to 3.0, which is a flat
line with noise on it rather than the trend the measurements above show.
That is what 6000 trials a bisection step buys against a 1e-3 budget -- six
expected events -- so the fix is re-measurement below ratio 1.5 with enough
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
