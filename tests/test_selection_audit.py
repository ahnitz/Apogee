"""Selection diagnostics must expose missing cost/calibration coverage."""
import importlib.util
from pathlib import Path
import numpy as np


def test_missing_measurements_are_not_silently_timed(monkeypatch):
    path = Path(__file__).resolve().parents[1]/'tools'/'audit_selection.py'
    spec = importlib.util.spec_from_file_location('selection_audit', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.mf, 'choose_threshold',
                        lambda power,n,snr,fd,band: None if band == 64 else 3.)
    tuning = {'cost': {(1024, 64, 2, 8, 6., 1.): [],
                       (1024, 256, 2, 8, 6., 1.): []}}
    rows = {r['band']: r for r in module.candidate_coverage(np.ones(1024),1024,6.,.001,tuning)}
    assert set(rows) == {64,128,256,512}
    assert rows[64]['cost_rows'] == 1 and not rows[64]['runnable']
    assert rows[128]['threshold'] == 3 and rows[128]['runnable']
    assert rows[128]['cost_rows'] == 0
    assert rows[256]['runnable']
    assert rows[512]['runnable']
    assert rows[512]['cost_rows'] == 0


def test_exported_costs_round_trip_through_the_library(tmp_path):
    path = Path(__file__).resolve().parents[1]/'tools'/'audit_selection.py'
    spec = importlib.util.spec_from_file_location('selection_export', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = dict(n=1024, snr=6., data=8, templates=32, device='cpu',
                  flat_seconds=.002,
                  candidates=[dict(band=128, fraction=.9, beff=32., seconds=.001, cost_rows=1),
                              dict(band=64, fraction=.7, beff=32., seconds=.0001, cost_rows=0)])
    output = tmp_path/'cost.txt'
    module.export_cost(result, output)
    table = module.mf._load_tuning(str(output))
    assert {key[1] for key in table['cost']} == {128}
    for taps in (4,8):
        assert table['cost'][(1024,128,2,taps,6.,1.)] == [(.9,32.,.5)]
