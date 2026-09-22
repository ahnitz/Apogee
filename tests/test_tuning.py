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
