"""A REAL reference profile, and what it shows the synthetic ones do not.

Every accuracy and threshold number in this library was calibrated against
`hmf_tune.make_ref`, a synthetic profile built to hit a target (f, B_eff).
The key assumption is that those two numbers determine how the coarse gate
behaves. They do not.

`tests/data/reference_profile_pycbc.npy` is the whitened signal power
profile |H(f)|^2 / S(f) from a live pycbc inspiral search, supplied in the
fdr-overshoot handoff: n=4096, 0.5 Hz per bin, zeroed outside [20 Hz,
Nyquist], sums to 1, peak at bin 78. It is here because at band 1024 it
sits at the SAME (f, B_eff) as a synthetic reference and is dismissed
11.7x more often -- measured, at an identical gate.

The reason is scalloping. The coarse statistic is about

    snr * sqrt(f) * g

where g is the worst-case loss from the coarse lag grid landing between
samples. B_eff is a second-moment PROXY for g, and a peaked profile with a
long tail breaks the proxy: at band 1024 the real profile has g=0.896
against the synthetic's 0.931, which puts its coarse statistic at 4.45
against a gate of 4.41 -- marginal -- where the synthetic sits at 4.63 with
room to spare.

Across ten profile shapes the correlation with log dismissal is -0.49 for
the current key, -0.93 for g, and -0.96 for snr*sqrt(f)*g.
"""
import pathlib

import numpy as np
import pytest

import matchedfilter as mf

DATA = pathlib.Path(__file__).parent / "data" / "reference_profile_pycbc.npy"


def real_profile():
    return np.load(DATA).astype(np.float64)


def scallop(p, band, n, m=48):
    """Worst-case coarse-grid loss, in closed form from the profile.

    The coarse stage searches a lag grid of spacing n/band, so the true peak
    can fall up to half a step away. This is the smallest |A(d)| over that
    half-step, where A is the normalised in-band correlation.
    """
    q = np.asarray(p[:band], dtype=np.float64)
    if q.sum() <= 0:
        return 0.0
    q = q / q.sum()
    ds = np.linspace(0.0, n / (2.0 * band), m)
    return float(np.abs(np.exp(2j * np.pi * np.outer(ds, np.arange(band)) / n) @ q).min())


def test_the_real_profile_is_what_it_claims():
    p = real_profile()
    assert p.shape == (4096,)
    assert abs(p.sum() - 1.0) < 1e-5
    assert int(p.argmax()) == 78
    # recovery factors quoted in the handoff, which selection reads
    for band, want in ((256, 0.7876), (512, 0.9306), (1024, 0.9870)):
        f, _ = mf._band_features(p, band)
        assert abs(f - want) < 1e-3, "band %d recovery %.4f, expected %.4f" % (band, f, want)


def test_band_and_beff_do_not_determine_the_gate_behaviour():
    """The key is insufficient, stated as the property rather than the number.

    A synthetic reference matched to the real one on (f, B_eff) should
    behave the same if those two are the whole story. Their scalloping
    factors differ, and that is what the threshold table cannot see.
    """
    p = real_profile()
    n, band = 4096, 1024
    f, be = mf._band_features(p, band)
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "tools"))
    import hmf_tune as t
    synth = t.make_ref(n, band, f, be)
    fs, bes = mf._band_features(synth, band)
    assert abs(fs - f) < 5e-3 and abs(bes - be) / be < 0.05, "not matched on the key"
    g_real, g_syn = scallop(p, band, n), scallop(synth, band, n)
    assert abs(g_real - g_syn) > 0.02, (
        "the two references have the same (f, B_eff) AND the same scalloping "
        "(%.4f vs %.4f) -- if that ever becomes true the key may be "
        "sufficient after all and this test should be revisited" % (g_real, g_syn))


def test_each_band_meets_its_requested_budget():
    """Gates target a common budget, not monotone realized rates across bands.

    The old xfail compared rates at different, independently chosen gates.
    A conservative narrow-band gate can legitimately dismiss less than a
    wider-band gate. What matters is that each stays within its own budget.
    """
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "tools"))
    import hmf_tune as t
    p = real_profile()
    n, snr, fd = 4096, 5.0, 1e-2
    for band in (256, 512, 1024):
        gate = mf.choose_threshold(p, n, snr, fd, band)
        assert gate is not None
        rate, detected, _ = t.measure(n, band, 2, 8, snr, 12000, power=p, thr=gate)
        assert detected * fd > 50, "insufficient statistical power"
        assert rate <= 1.7 * fd, (band, gate, rate, detected)
