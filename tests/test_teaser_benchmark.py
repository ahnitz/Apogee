"""The teaser must measure the same public API on CPU and GPU."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest


@pytest.mark.parametrize('device', ['cpu', 'gpu'])
@pytest.mark.parametrize('kind', ['flat', 'hier'])
def test_teaser_times_public_run(monkeypatch, device, kind):
    path = Path(__file__).resolve().parents[1] / 'tools' / 'teaser_figure.py'
    spec = importlib.util.spec_from_file_location('teaser_timing_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    elapsed = [0.0]

    class Filter:
        def __init__(self, *args, **kwargs):
            pass

        def set_reference(self, value):
            pass

        def set_data(self, value):
            pass

        def set_templates(self, value):
            pass

        def run(self, **kwargs):
            calls.append(kwargs)
            elapsed[0] += 0.002

    monkeypatch.setattr(module.mf, 'MatchedFilter', Filter)
    monkeypatch.setattr(module.mf, 'HierarchicalFilter', Filter)
    monkeypatch.setattr(module, '_case', lambda: (np.zeros(1), np.zeros(1)))
    monkeypatch.setattr(module, '_reference', lambda: (np.ones(1), np.ones(1)))
    monkeypatch.setattr(module.time, 'perf_counter', lambda: elapsed[0])
    result = getattr(module, device + '_ms')(kind, reps=4)
    assert result == pytest.approx(2.0)
    assert len(calls) > 4  # warmup also uses the same API
    assert all(c == {'binsize': module.N, 'threshold': 5.5} for c in calls)
