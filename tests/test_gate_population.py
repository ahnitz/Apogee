"""What the coarse gate keeps and what it drops, by POPULATION.

`fd` is a promise about SIGNALS. It is not a promise that the hierarchical
filter reproduces the flat filter's trigger list, and on marginal noise the
two differ by a lot -- 27% to 38% of pure-noise triggers at threshold 5.0
are dismissed at the bands selection actually picks, against an `fd` of
1e-3 that is met with room to spare on the same data.

Both halves are asserted here because each one, alone, invites the wrong
fix. Seeing the noise loss without the signal measurement reads as a
calibration defect and the repair is to lower the gate, which throws the
speedup away. Seeing the signal measurement without the noise loss leaves a
user to discover on their own that the two filters disagree about their
trigger lists.

The mechanism is not a defect and the third case pins it: a coherent signal
deposits power across frequency exactly as the template does, so the
in-band fraction f applies and the coarse statistic is about sqrt(f) times
the full one, every time. A noise fluctuation that reaches the threshold got
there by a draw, and its in-band part is an INDEPENDENT draw with the same
mean and a large variance -- so a good share of marginal noise triggers land
under the gate while signals at the same |z| do not. Where f is 1.0 the
coarse statistic IS the full one and nothing can be dismissed at all, which
is what band 2048 measures on this reference.

Measured on twelve captured PyCBC segments (not in the repo, so not
asserted here, but this is the observation these bounds come from):

    band   flat noise triggers      injections at snr 5.2
           dismissed of 842         dismissed of 2400
     256      48   5.7e-2               0   (< 4.2e-4)
     512      20   2.4e-2               0
    1024       3   3.6e-3               0
    2048       0   0                    --  (f = 1.0000)

Selection picks band 512 for that reference.
"""
import numpy as np
import pytest

import matchedfilter as mf
from test_api import inspiral_power, template_with_power, noise


N = 4096
SNR = 5.0
#: The budget the NOISE half is compared against, and the tightest one this
#: file's trial count could resolve if it had to.
FD = 1e-3
#: The budget the INJECTION half asserts. Deliberately looser than FD: at
#: ~500 injections a 1e-3 rate is half an expected event, so a run that saw
#: two would "fail" at p = 0.1 and a run that saw none would prove nothing.
#: 1e-2 over the same trials expects ~5 and separates. The contrast this file
#: exists to show survives either way -- marginal noise triggers are lost at
#: 27-38%, which is 30x this and 300x FD.
FD_INJ = 1e-2


def _bank(nt=16):
    return np.stack([template_with_power(N, inspiral_power(N, exponent=e))
                     for e in np.linspace(-7 / 3.0, -4 / 3.0, nt)])


def _noise_trigger_loss(band, reps=12, nb=64):
    """(flat triggers, of which the gate dismissed) on pure noise."""
    rng = np.random.default_rng(5)
    power = inspiral_power(N)
    H = _bank()
    flat = mf.MatchedFilter(N, nb, H.shape[0])
    flat.set_templates(H)
    hier = mf.HierarchicalFilter(N, nb, H.shape[0], snr=SNR, fd=FD,
                                 band=band, taps=8)
    hier.set_reference(power)
    hier.set_templates(H)
    total = missed = 0
    for _ in range(reps):
        D = noise((nb, N), rng)
        flat.set_data(D)
        hier.set_data(D)
        a = flat.run(binsize=N, threshold=SNR)
        b = hier.run(binsize=N, threshold=SNR)
        fi, hi = a["index"], b["index"]
        total += int((fi >= 0).sum())
        missed += int(((fi >= 0) & (hi < 0)).sum())
        # The one-sided guarantee holds on this population too: the gate may
        # dismiss, never promote.
        assert int(((fi < 0) & (hi >= 0)).sum()) == 0, \
            "band %d: the gate promoted a trigger the flat filter never had" % band
    return total, missed


@pytest.mark.parametrize("band", (512, 1024))
def test_injected_signals_meet_the_budget(band):
    """The promise `fd` actually makes, on the population it is about.

    The bank matches the reference here, which is the documented contract:
    the reference states how SNR accumulates for the bank being filtered.

    A bank that does NOT match its reference is a separate question and an
    open one. Run this with _bank() spanning exponents -7/3 to -4/3 against
    a reference at -7/3 and it omits 66 of 508 injections at band 512, 130x
    the budget. That is not obviously a defect -- one reference cannot
    describe a heterogeneous bank -- but it is not obviously misuse either,
    because a real template bank IS heterogeneous, and the twelve captured
    PyCBC segments pass with 0 of 2400 dismissed while their 37 templates
    span an in-band fraction of 0.31 to 0.61 against a reference at 0.93. A
    wider spread than the synthetic case that fails. So the spread alone is
    not the mechanism and the question is still open; see
    docs/hierarchical.md.
    """
    rng = np.random.default_rng(23)
    power = inspiral_power(N)
    H = np.stack([template_with_power(N, power) for _ in range(16)])
    nt = H.shape[0]
    nb = 64
    flat = mf.MatchedFilter(N, nb, nt)
    flat.set_templates(H)
    hier = mf.HierarchicalFilter(N, nb, nt, snr=SNR, fd=FD_INJ, band=band,
                                 taps=8)
    hier.set_reference(power)
    hier.set_templates(H)

    ph = np.exp(2j * np.pi * np.arange(N) / N)
    detected = omitted = 0
    for r in range(12):
        D = noise((nb, N), rng)
        which = rng.integers(0, nt, nb)
        for b in range(nb):
            t = which[b]
            lag = int(rng.integers(0, N))
            D[b] += (1.04 * SNR * H[t] * ph ** lag).astype(np.complex64)
        flat.set_data(D)
        hier.set_data(D)
        a = flat.run(binsize=N, threshold=SNR)
        b_ = hier.run(binsize=N, threshold=SNR)
        for b in range(nb):
            t = which[b]
            if a["index"][b, t, 0] >= 0:
                detected += 1
                omitted += int(b_["index"][b, t, 0] < 0)
    assert detected * FD_INJ > 3, \
        "only %d detections: %.1f events expected at a %.0e budget, which " \
        "cannot separate a pass from a failure" % (detected, detected * FD_INJ,
                                                   FD_INJ)
    rate = omitted / detected
    # 3x absorbs binomial scatter: at ~5 expected events P(>=15) is 2e-4, so
    # this fails on a real regression and not on a draw.
    assert rate <= FD_INJ * 3, \
        "band %d omitted %d of %d injections, %.2e against a %.0e budget" \
        % (band, omitted, detected, rate, FD_INJ)


def test_marginal_noise_triggers_are_dismissed_and_that_is_not_the_budget():
    """The flat filter's marginal NOISE triggers do not all survive.

    Asserted as a floor, not a ceiling: the point is that this number is
    nothing like `fd`, so it cannot be read as a budget violation and
    "fixed" by lowering the gate. A build where this went to zero would
    have stopped gating.
    """
    total, missed = _noise_trigger_loss(512)
    assert total > 40, "too few noise triggers to say anything: %d" % total
    rate = missed / total
    assert rate > 10 * FD, (
        "only %.2e of marginal noise triggers were dismissed at band 512. "
        "Either the gate stopped gating, or this population now behaves "
        "like the signal population -- both are worth knowing" % rate)


def test_a_full_band_gate_dismisses_nothing():
    """f = 1.0 means the coarse statistic IS the full one.

    The mechanism check. If noise triggers were being lost to anything
    other than the in-band fraction -- an indexing error, a threshold
    conversion, a scan bug -- it would still lose them here, where there is
    no band restriction left to lose them to.
    """
    power = inspiral_power(N)
    f, _be = mf._band_features(power, 2048)
    assert f > 0.999, "expected a full-band fraction at 2048, got %.4f" % f
    total, missed = _noise_trigger_loss(2048)
    assert total > 40, "too few noise triggers to say anything: %d" % total
    assert missed == 0, \
        "band 2048 dismissed %d of %d triggers where f = %.4f leaves nothing " \
        "out of band" % (missed, total, f)
