"""Keep measured selection regressions covered after retiring accuracy rows."""
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


def test_partial_cost_coverage_does_not_hide_candidates():
    p = _inspiral_power(4096)
    t = {'cost': {(4096, 256, 2, 8, 5.): [(.8, 100., 1.)],
                  (4096, 512, 2, 8, 5.): [(.9, 200., 2.)],
                  (4096, 512, 2, 8, 5.75): [(.9, 200., 2.)]}}
    for snr in (5., 5.75):
        candidates = mf._cost_candidates(p, 4096, snr, t)
        assert {c['band'] for c in candidates} == {256, 512}
        assert mf.choose_config(p, 4096, snr, .01, t) == (256, 8)
