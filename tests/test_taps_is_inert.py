"""`taps` is configuration metadata, not a control. Pinned, because the
accuracy table still has an axis for it.

HierarchicalFilter's own docstring: "taps remains configuration metadata
for existing tables; execution uses the raw coarse maximum without
interpolation." The CPU used to interpolate the coarse peak and stopped --
"it cost more in taps than the correlations it saved."

That leaves an axis in ACC2 measuring a parameter with no effect, which is
half of every length ever measured. tools/regen/accuracy.py now measures
one value of K and emits the rest, and these tests are what make that
safe: if interpolation is ever reintroduced, taps starts mattering, and
this file fails before a table is rebuilt on a false assumption.
"""
import pathlib
import sys

import numpy as np
import pytest

import matchedfilter as mf

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "tools"))

PROFILE = pathlib.Path(__file__).parent / "data" / "reference_profile_pycbc.npy"


@pytest.mark.parametrize("band", [512, 1024])
def test_dismissal_does_not_move_with_taps(band):
    """The measured quantity the ACC2 axis exists to capture."""
    import hmf_tune as t
    p = np.load(PROFILE).astype(np.float64)
    n, snr, thr = 4096, 5.0, 4.4
    out = {}
    for K in (2, 4, 8):
        dm, _, _ = t.measure(n, band, 2, K, snr, 6000, power=p, thr=thr)
        out[K] = dm
    assert out[2] == out[4] == out[8], (
        "taps changed the dismissal rate (%s) -- interpolation is back, so "
        "the ACC2 K axis is load-bearing again and MEASURE_K in "
        "tools/regen/accuracy.py must widen to match" % out)


def test_the_shipped_table_has_no_information_on_the_taps_axis():
    """Every K pair in the shipped table is identical, or the axis matters."""
    import collections
    path = pathlib.Path(mf.__file__).parent / "accuracy.txt"
    cells = collections.defaultdict(dict)
    for ln in path.read_text().splitlines():
        if ln.startswith("ACC2 "):
            w = ln.split()
            cells[(int(w[1]), float(w[3]), float(w[4]),
                   float(w[5]), float(w[6]))][int(w[2])] = float(w[7])
    pairs = [v for v in cells.values() if len(v) > 1]
    if not pairs:
        pytest.skip("table carries a single taps value")
    differ = [v for v in pairs if len(set(v.values())) > 1]
    assert not differ, (
        "%d of %d cells differ across taps -- the axis carries information "
        "and collapsing it in the sweep would lose it; first: %s"
        % (len(differ), len(pairs), differ[0]))
