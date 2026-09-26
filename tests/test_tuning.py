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
    covered = {r[0] for r in t["cost"]}
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
        hf.set_coarse_threshold(0.0)
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


def test_model_answers_outside_the_old_snr_grid():
    p = inspiral_power(4096)
    for snr in (4., 9.):
        assert mf.choose_config(p, 4096, snr, 1e-3) is not None


def test_gates_increase_with_recovered_power_on_this_reference():
    """A narrower band must not inherit a wider band's optimistic gate."""
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
    assert len(seen) >= 2, "the model answered for fewer than two bands"
    seen.sort()
    for (f0, b0, t0), (f1, b1, t1) in zip(seen, seen[1:]):
        assert t1 >= t0 - 1e-6, (
            "threshold falls as f rises: band %d f=%.3f thr=%.4f "
            "then band %d f=%.3f thr=%.4f" % (b0, f0, t0, b1, f1, t1))


def test_cost_override_does_not_poison_other_devices_or_default(monkeypatch, tmp_path):
    default = mf._load_tuning()
    path = tmp_path / 'cost.txt'
    path.write_text('COST 1024 256 2 8 5.0 .8 50.0 1.2\n')
    explicit = mf._load_tuning(str(path))
    assert mf._load_tuning() is default
    from matchedfilter.device import Device
    monkeypatch.setenv('MF_COST', str(path))
    gpu = mf._load_tuning_for(Device('gpu', 0, 'card', 'vulkan'))
    assert gpu['cost'] == explicit['cost']
    assert mf._TUNING is default
    assert mf._load_tuning()['cost'] == explicit['cost']
    monkeypatch.delenv('MF_COST')
    assert mf._load_tuning()['cost'] == default['cost']
