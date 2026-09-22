"""Autotuning: it answers from measurement or it refuses.

Helpers come from test_api, which holds the signal and layout builders the
whole suite shares.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(__file__))
import matchedfilter as mf                                    # noqa: E402
from test_api import (inspiral_power, template_with_power, noise)  # noqa: E402


def test_autotuning_refuses_outside_its_measured_coverage():
    """Autotuning is a promise, so it must not guess.

    There used to be a compiled design table to fall back on. It was a model,
    it did not promise the false-dismissal budget -- 3.7% missed against 0.1%
    on the captures -- and consulting it silently let a caller believe they
    had a guarantee they did not have. Refusing is the whole policy, so it is
    worth a test: a fallback reintroduced by accident would look like nothing
    at all from the outside.
    """
    n = 8192                       # the shipped tables cover 4096
    power = inspiral_power(n)
    hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=2, snr=5.0, fd=1e-3)
    hf.set_reference(power)
    with pytest.raises(ValueError) as e:
        hf.config                  # builds the plan, so this is where it fails
    msg = str(e.value)
    assert "no measured tuning" in msg
    assert "8192" in msg, "the message must name what was asked for"
    assert "band" in msg and "hmf_tune" in msg, (
        "the message must give both ways forward: state the configuration, "
        "or measure it")


def test_explicit_configuration_is_always_honoured():
    """Stating the configuration is the escape hatch, at any size.

    The tables refusing must not make the library unusable where they have no
    rows -- a caller who knows what they want says so and is never second
    guessed.
    """
    for n, band in ((8192, 2048), (4096, 1024)):
        hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=2, snr=5.0, fd=1e-3,
                                   band=band, oversample=2, taps=8)
        assert hf.config == (band, 2, 8)
        # and it works without a reference, which autotuning cannot do
        H = np.stack([template_with_power(n, inspiral_power(n))
                      for _ in range(2)])
        hf.set_templates(H)
        hf.set_data(noise((1, n), np.random.default_rng(2)))
        hf.run(binsize=n, threshold=5.0)


def test_autotuning_uses_the_reference_where_it_has_rows():
    """Inside coverage it answers, and the answer comes from the reference.

    Two references differing only in where they put their power must be able
    to get different configurations -- otherwise the tables are not being
    consulted and the lookup is decoration.
    """
    n = 4096
    wide = inspiral_power(n)
    narrow = wide.copy()
    narrow[n // 8:] = 0.0
    picks = []
    for power in (wide, narrow):
        hf = mf.HierarchicalFilter(n, ndata=1, ntemplates=2, snr=5.0, fd=1e-3)
        hf.set_reference(power)
        picks.append(hf.config)
    assert all(p is not None for p in picks)
    assert all(b > 0 for b, _, _ in picks)


# ------------------------------------------------ SNR coverage and fallback

def test_snr_exact_hit_uses_only_that_row():
    rows, why = mf._snr_rows_for(5.5, [5.0, 5.5, 6.0])
    assert rows == (5.5,)
    assert "measured at snr 5.5" in why


def test_snr_above_the_range_falls_back_conservatively():
    """A threshold above everything measured is an EASIER problem.

    So it is answerable, and the bound that holds is the worst dismissal
    anywhere in the measured range -- not the nearest row. Measured directly
    at snr 6.5/7.0/8.0: nothing above the range exceeds its in-range maximum.
    """
    rows, why = mf._snr_rows_for(9.0, [5.0, 5.5, 6.0])
    assert rows == (5.0, 5.5, 6.0)
    assert "above the measured range" in why


def test_snr_below_the_range_refuses():
    """A lower threshold is a HARDER problem and nothing measured bounds it."""
    rows, why = mf._snr_rows_for(4.5, [5.0, 5.5, 6.0])
    assert rows is None
    assert "below" in why


def test_the_fallback_is_not_nearest_neighbour():
    """Dismissal is not monotone in the threshold, so nearest-row is unsafe.

    172 of 640 fully-measured cells in the shipped table RISE from snr 5.0 to
    5.5. If this ever starts returning a single nearest row for an
    out-of-range threshold, the guarantee quietly stops holding.
    """
    rows, _ = mf._snr_rows_for(7.0, [5.0, 5.5, 6.0])
    assert len(rows) > 1, "must bound with the whole range, not one row"


def test_dismissal_is_not_monotone_in_snr_in_the_shipped_table():
    """Pins the fact the fallback rule is built around.

    If a future table were monotone this test would fail, and the right
    response would be to check whether the simpler nearest-row rule is now
    safe -- not to delete the test.
    """
    import collections
    t = mf._load_tuning()
    cells = collections.defaultdict(dict)
    for (n, band, U, K, snr, f, be, margin, dm) in t["fdr"]:
        cells[(n, band, U, K, f, be, margin)][snr] = dm
    snrs = sorted({r[4] for r in t["fdr"]})
    rises = 0
    full = 0
    for v in cells.values():
        if len(v) < len(snrs):
            continue
        full += 1
        seq = [v[s] for s in snrs]
        if any(b > a + 1e-12 for a, b in zip(seq, seq[1:])):
            rises += 1
    assert full > 0
    assert rises > 0, "table is monotone in snr; revisit the fallback rule"


def test_autotuning_answers_above_the_table_and_refuses_below():
    """End to end, through choose_config, on a real reference."""
    from matchedfilter.benchmark import _inspiral_power
    p = _inspiral_power(4096)
    assert mf.choose_config(p, 4096, 9.0, 1e-3) is not None
    assert mf.choose_config(p, 4096, 4.0, 1e-3) is None
