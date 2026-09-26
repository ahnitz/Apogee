"""Selection must be monotone in the threshold, because accuracy is.

Dismissal falls as the signal gets louder. So a HIGHER threshold is an
easier problem, and the configuration chosen for it can never be more
expensive than the one chosen for a lower threshold. The first stage may
narrow as the threshold rises; it must never widen.

This is not a preference. It is forced by what the tables measure, which
means a violation is always a defect somewhere in the lookup -- and it has
been, twice:

  * the gate axis: dismissal vs gate inverted in 665 of 1120 measured
    curves, and `_margin_at_budget` interpolated by scanning for a
    bracketing interval, which is only well defined on a monotone curve.
  * the coverage rule: at n=16384 snr 5.75 exactly ONE configuration of 48
    had been measured. That was enough for `_snr_rows_for` to call 5.75
    "measured", so the bracketing rule never fired and 47 of 48 candidates
    were priced from an empty column. Selection picked band 1024 where 5.5
    and 6.0 both pick 2048, and ran 2.9x slower at the EASIER threshold.

Both were invisible to every other test: the filter returned correct
peaks, just from a badly chosen configuration, so only a timing comparison
or this invariant could see it.
"""
import numpy as np
import pytest

import matchedfilter as mf
from matchedfilter.benchmark import _inspiral_power

SNRS = (5.0, 5.5, 5.75, 6.0, 6.5)


@pytest.mark.parametrize("n", [1024, 2048, 4096, 8192, 16384])
@pytest.mark.parametrize("fd", [1e-2, 1e-3])
def test_chosen_band_never_widens_as_the_threshold_rises(n, fd):
    power = _inspiral_power(n)
    t = mf._load_tuning()
    chosen = []
    for snr in SNRS:
        cfg = mf.choose_config(power, n, snr, fd, t)
        if cfg is not None:
            chosen.append((snr, cfg[0]))
    if len(chosen) < 2:
        pytest.skip("n=%d fd=%g: fewer than two thresholds covered" % (n, fd))
    for (s0, b0), (s1, b1) in zip(chosen, chosen[1:]):
        assert b1 <= b0, (
            "n=%d fd=%g: band WIDENS from %d at snr %s to %d at snr %s. "
            "A higher threshold is an easier problem, so it cannot need a "
            "wider first stage -- this is a lookup defect, and it costs "
            "real time at the easier threshold." % (n, fd, b0, s0, b1, s1))


@pytest.mark.parametrize("n", [1024, 2048, 4096, 8192, 16384])
def test_no_threshold_row_is_used_on_minority_coverage(n):
    """A row measured for a handful of configurations cannot rank them all.

    The guard lives in choose_config; this asserts the property it exists
    to produce, so moving or rewriting the guard cannot silently drop it.
    """
    t = mf._load_tuning()
    tsnrs = t["snrs_at"].get(n)
    if not tsnrs:
        pytest.skip("no old-key rows at n=%d" % n)
    cov = {s: len({(r[1], r[2], r[3], r[7])
                   for r in t["by_ns"].get((n, s), ())}) for s in tsnrs}
    full = max(cov.values())
    thin = [s for s in tsnrs if cov[s] * 2 < full]
    power = _inspiral_power(n)
    for s in thin:
        # the thin row must not be what selection reads: the configuration
        # it yields has to match what its neighbours yield, not the outlier
        # the thin column would name.
        near = [x for x in tsnrs if cov[x] * 2 >= full]
        if not near:
            continue
        lo = max([x for x in near if x <= s], default=min(near))
        got = mf.choose_config(power, n, s, 1e-2, t)
        ref = mf.choose_config(power, n, lo, 1e-2, t)
        if got is None or ref is None:
            continue
        assert got[0] <= ref[0], (
            "n=%d: snr %s is measured for only %d of %d configurations, and "
            "selection is still reading it -- band %d against %d at the "
            "fully covered snr %s below it"
            % (n, s, cov[s], full, got[0], ref[0], lo))


def test_dismissal_curves_are_monotone_after_the_envelopes():
    """Both envelopes, at the point selection actually consumes them."""
    assert mf._snr_envelope({5.0: 0.02, 5.5: 0.03, 6.0: 0.01}) == {
        5.0: 0.03, 5.5: 0.03, 6.0: 0.01}, "snr envelope must be non-increasing"
    env = mf._snr_envelope({5.0: 0.05, 5.5: 0.04, 6.0: 0.01})
    vals = [env[s] for s in sorted(env)]
    assert all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
    # and it must never understate: the repair direction is toward escalating
    raw = {5.0: 0.02, 5.5: 0.03}
    assert all(mf._snr_envelope(raw)[s] >= raw[s] for s in raw)
