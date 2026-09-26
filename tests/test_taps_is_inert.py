"""Taps is metadata: execution and model use the raw coarse maximum."""
import pathlib
import sys

import numpy as np
import pytest

import matchedfilter as mf

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "tools"))

PROFILE = pathlib.Path(__file__).parent / "data" / "reference_profile_pycbc.npy"


@pytest.mark.parametrize("band", [512, 1024])
def test_dismissal_does_not_move_with_taps(band):
    """Changing inert metadata must not invalidate the gate model."""
    import hmf_tune as t
    p = np.load(PROFILE).astype(np.float64)
    n, snr, thr = 4096, 5.0, 4.4
    out = {}
    for K in (2, 4, 8):
        dm, _, _ = t.measure(n, band, 2, K, snr, 6000, power=p, thr=thr)
        out[K] = dm
    assert out[2] == out[4] == out[8], (
        "taps changed the dismissal rate (%s) -- interpolation is back, so "
        "the gate model must account for it" % out)
