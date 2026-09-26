"""A reference profile describes a matched bank, not every heterogeneous bank.

Keeping all spectral power still decimates the lag grid. Full-band
scalloping depends on the profile, so f=1 does not imply zero dismissal.
"""
import numpy as np
import pytest
import matchedfilter as mf
from matchedfilter import gatemodel
from test_api import inspiral_power, template_with_power
from _gatelib import noise_trigger_loss


def test_full_band_matched_reference_noise_triggers():
    p = inspiral_power(4096)
    h = np.stack([template_with_power(4096, p)] * 16)
    total, missed = noise_trigger_loss(4096, h, p, 2048, 5., .001)
    assert total > 40
    # Fixed-seed regression, not a universal zero-dismissal guarantee.
    assert missed == 0


def test_a_heterogeneous_bank_needs_more_than_one_reference():
    n, band = 4096, 2048
    narrow = inspiral_power(n)
    broad = inspiral_power(n, exponent=-4/3)
    assert mf._band_features(narrow, band)[0] > .999999
    assert mf._band_features(broad, band)[0] > .999999
    gate = gatemodel.gate_for(narrow, n, band, 5., .001)
    broad_gate = gatemodel.gate_for(broad, n, band, 5., .001)
    assert broad_gate < .85 * gate
    assert gatemodel.dismissal(broad, n, band, 5., gate) > .05


def test_full_spectral_coverage_still_scallops_between_grid_lags():
    n, band = 1024, 512
    p = np.zeros(n); p[:band] = 1
    h = np.sqrt(p / p.sum()).astype(np.complex64)
    # An odd fine-grid lag lies halfway between coarse samples.
    d = (5.1 * h * np.exp(2j*np.pi*np.arange(n)/n)).astype(np.complex64)
    flat = mf.MatchedFilter(n)
    hier = mf.HierarchicalFilter(n, band=band)
    hier.set_reference(p); hier.set_coarse_threshold(4.)
    for f in (flat, hier):
        f.set_templates(h[None]); f.set_data(d[None])
    assert flat.run(threshold=5.)['index'].item() >= 0
    assert hier.run(threshold=5.)['index'].item() < 0
