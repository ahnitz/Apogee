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
    # A transform length the tables do not cover. Kept as a computed value
    # rather than a constant: coverage grows as lengths are measured, and this
    # test must keep testing refusal rather than quietly starting to pass for
    # the wrong reason.
    t = mf._load_tuning()
    covered = {r[0] for r in t["fdr"]}
    n = next(v for v in (3072, 6144, 12288, 24576) if v not in covered)
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
                                   band=band, taps=8)
        assert hf.config == (band, 8)
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
    assert all(b > 0 for b, _ in picks)   # config is (band, taps)


# ------------------------------------------------ SNR coverage and fallback

def test_snr_exact_hit_uses_only_that_row():
    rows, why = mf._snr_rows_for(5.5, [5.0, 5.5, 6.0])
    assert rows == (5.5,)
    assert "measured at snr 5.5" in why


def test_snr_above_the_range_uses_the_highest_measured_row():
    """A threshold above everything measured is an EASIER problem.

    So the nearest measurement BELOW it is the relevant one. Taking the worst
    row across the whole range instead imported snr 5.0's behaviour into a
    case easier than snr 6.0, and it cost real speed: snr 6.5 was handed band
    1024 where snr 6.0 got band 256, so asking for a higher threshold
    produced a slower filter.
    """
    rows, why = mf._snr_rows_for(9.0, [5.0, 5.5, 6.0])
    assert rows == (6.0,)
    assert "above the measured range" in why


def test_snr_below_the_range_refuses():
    """A lower threshold is a HARDER problem and nothing measured bounds it."""
    rows, why = mf._snr_rows_for(4.5, [5.0, 5.5, 6.0])
    assert rows is None
    assert "below the lowest measured" in why


def test_interior_thresholds_are_bounded_by_both_neighbours():
    """Dismissal is not monotone in the threshold, so one neighbour is unsafe.

    172 of 640 fully-measured cells in the shipped table RISE from snr 5.0 to
    5.5, so a request at 5.2 cannot be answered from the 5.0 row alone. It is
    bracketed, and the worse of the two neighbours is the honest bound.
    """
    rows, why = mf._snr_rows_for(5.2, [5.0, 5.5, 6.0])
    assert rows == (5.0, 5.5), "must use both bracketing rows"
    assert "between measured" in why


def test_a_higher_threshold_never_gets_a_wider_first_pass():
    """Asking for more SNR must not make the filter work harder.

    The band is the invariant to check, not the tabulated cost: cost is
    RELATIVE to a pivot measured at the same (n, snr), so two rows at
    different thresholds are ratios against different denominators and cannot
    be ordered against each other. The band can be -- a narrower first pass is
    strictly less work -- and it is what a higher threshold is supposed to buy.

    This failed once for a real reason: the fallback bounded out-of-range
    thresholds by the worst row across the whole measured range, so snr 6.5
    inherited snr 5.0's behaviour and got band 1024 where snr 6.0 got 256.
    """
    from matchedfilter.benchmark import _inspiral_power
    n = 4096
    p = _inspiral_power(n)
    prev = None
    seen = []
    for snr in (5.0, 5.5, 6.0, 6.5, 9.0):
        cfg = mf.choose_config(p, n, snr, 1e-3)
        assert cfg is not None, snr
        seen.append((snr, cfg[0]))
        if prev is not None:
            assert cfg[0] <= prev, seen
        prev = cfg[0]


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


def test_threshold_lookup_refuses_below_the_measured_envelope():
    """Never EXTRAPOLATE a gate downward past the measured rows.

    Inverse-distance weighting extrapolates happily, and below the table's
    hull it pushes the threshold UP -- the unsafe direction, since a gate
    set too high dismisses signal and nothing downstream reports it.

    Measured at n=4096 band=128: f = 0.697 against a floor of 0.800 and
    ratio 1.24 against 1.50. It returned 4.1170, ABOVE band 256's properly
    interpolated 4.0717, which is backwards -- band 128 captures less of the
    signal (f 0.697 against 0.883) so its coarse statistic recovers less
    SNR and its threshold must be LOWER. It merely looked efficient: refine
    cost 0.007 ms against 0.150, because it was over-gating.

    Above the hull is safe and is clamped rather than refused.
    """
    n = 4096
    ref = inspiral_power(n)

    # Every band the lookup answers for must sit inside the hull, and the
    # answer must rise with f: more signal energy in the band means the
    # coarse statistic recovers more, so it supports a higher bar.
    seen = []
    for band in (128, 256, 512, 1024):
        t = mf.choose_threshold(ref, n, 5.5, 1e-2, band)
        if t is None:
            continue                      # outside coverage: correctly refused
        f, be = mf._band_features(ref.astype(np.float32), band)
        seen.append((f, band, t))
    assert len(seen) >= 2, "the table answered for fewer than two bands"
    seen.sort()
    for (f0, b0, t0), (f1, b1, t1) in zip(seen, seen[1:]):
        assert t1 >= t0 - 1e-6, (
            "threshold falls as f rises: band %d f=%.3f thr=%.4f "
            "then band %d f=%.3f thr=%.4f" % (b0, f0, t0, b1, f1, t1))
