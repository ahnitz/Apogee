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

def test_dismissal_lookup_brackets_below_the_query():
    """B_eff is not monotonic, so rows above the query are not a bound.

    Measured at n=4096 band 256 f=0.99 margin 1.00, dismissal runs 6.4e-2 at
    B_eff 1.1 down to 7.2e-4 at 25.6 and back up to 6.9e-3 at 463. Taking
    only rows at or above the query reported the 8e-4 it could see where the
    truth was 6.4e-2, which is how a configuration losing 10% of its peaks
    passed as admissible.
    """
    # (f, B_eff, dismissal) on the FALLING branch: worse as B_eff drops
    rows = [(0.99, 1.2, 5.0e-2), (0.99, 3.5, 3.0e-2), (0.99, 25.6, 7.0e-4)]
    # a query between the two low rows must see the worse one below it
    got = mf._cover_dismissal(rows, 0.99, 2.0)
    assert got == pytest.approx(5.0e-2), got
    # sitting above every row, the rows above are empty and the nearest
    # below still speaks
    assert mf._cover_dismissal(rows, 0.99, 30.0) == pytest.approx(7.0e-4)
    # on the rising branch the rows above dominate, so nothing changes
    rise = [(0.99, 10.0, 3.0e-4), (0.99, 100.0, 2.0e-3), (0.99, 460.0, 7.0e-3)]
    assert mf._cover_dismissal(rise, 0.99, 50.0) == pytest.approx(7.0e-3)
    # and a query no row speaks for returns None rather than a guess
    assert mf._cover_dismissal([(0.80, 10.0, 1e-3)], 0.99, 5.0) is None


def test_margin_interpolation_refuses_an_unsampled_segment():
    """Interpolating onto the budget needs the segment to be sampled.

    At n=4096 band 256 B_eff 1.2 the step from margin 0.97 to 1.00 runs
    1.45e-3 to 5.62e-2. Interpolating that to land on 1e-2 returns 0.9858
    with no safety in it, and the FIR-search workload then loses 11 of 140
    against a 3% budget.
    """
    floor = 7.5e-4
    steep = [(0.97, 1.45e-3), (1.00, 5.62e-2)]      # 39x in one step
    assert mf._margin_at_budget(steep, 1e-2, floor) == pytest.approx(0.97)

    # under a decade the interpolation stands; that is where its speed came
    # from, 2.44x against 1.95x at n=4096 snr 5.5
    gentle = [(0.90, 3.0e-3), (0.94, 9.0e-3)]
    got = mf._margin_at_budget(gentle, 6.0e-3, floor)
    assert 0.90 < got < 0.94, got

    # the guard must not fire where no interpolation happens at all
    assert mf._margin_at_budget([(0.90, 1e-4), (1.00, 5e-4)], 1e-2,
                                floor) == pytest.approx(1.00)


def test_low_beff_rows_exist_where_real_references_live():
    """The shipped table must reach the B_eff that real references have.

    Both the FIR-search reference (1.1) and the tests' inspiral reference
    (1.9) sit below the fractional ladder's floor at every band. A table
    that stops at band/10 cannot say anything about either.
    """
    t = mf._load_tuning()
    floors = {}
    for r in t["fdr"]:
        key = (r[0], r[1])
        floors[key] = min(floors.get(key, 1e9), r[6])
    assert floors, "no accuracy rows loaded"
    bad = {k: v for k, v in floors.items() if v > 4.0}
    assert not bad, "B_eff floor above 4 for %d (n, band) pairs: %s" % (
        len(bad), sorted(bad.items())[:4])
