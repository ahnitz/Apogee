"""The computed gate repairs the old table's optimistic low-ratio corner."""
import numpy as np
import pytest
import matchedfilter as mf
from test_api import inspiral_power
from test_gate_model import filter_mc


@pytest.mark.parametrize('band', [128, 2048])
def test_gate_quantile_matches_filter_at_budget(band):
    p = inspiral_power(4096)
    gate = mf.choose_threshold(p, 4096, 5., .001, band)
    # ~60 events: enough to reject the old 2-29x errors. This independently
    # tests placement, not just dismissal at an arbitrary loose gate.
    observed = filter_mc(p, gate, trials=100000, band=band)
    assert observed < .0017, (band, gate, observed)
    if band == 2048:
        assert observed > .0005, (band, gate, observed)
    # At band 128 the local model omits remote coarse maxima, so it is
    # conservative. Do not claim a two-sided accuracy check for that regime.


def test_model_distinguishes_bands_with_identical_old_table_keys():
    import hmf_tune as ht
    gates = []
    for band in (128, 1024):
        p = ht.make_ref(4096, band, .70, band/1.20)
        gates.append(mf.choose_threshold(p, 4096, 5., .001, band))
    assert gates[0] != pytest.approx(gates[1], rel=1e-4), gates
