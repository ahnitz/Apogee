"""A hierarchy executes only with a supplied or explicitly chosen gate."""
import numpy as np
import pytest
import matchedfilter as mf
from conftest import usable_gpu


@pytest.fixture(params=['cpu', 'gpu'])
def device(request):
    if request.param == 'cpu':
        return 'cpu'
    gpu = usable_gpu()
    if gpu is None:
        pytest.skip('no usable GPU')
    return gpu


def inputs(n=1024):
    rng = np.random.default_rng(111)
    return [(rng.normal(size=(2, n)) + 1j*rng.normal(size=(2, n))).astype(np.complex64)
            for _ in range(2)]


@pytest.mark.parametrize('series', [False, True])
def test_missing_calibration_refuses_execution(device, monkeypatch, series):
    monkeypatch.setattr(mf, 'choose_threshold', lambda *a, **kw: None)
    f = mf.HierarchicalFilter(1024, 2, 2, band=256, device=device)
    f.set_reference(np.ones(1024))
    d, h = inputs()
    f.set_templates(h)
    f.set_data(d)
    with pytest.raises(ValueError, match='no calibrated coarse threshold'):
        if series:
            f.run_series(d[0], [0], [0], [1024])
        else:
            f.run()
    assert f.stats == (0, 0)


def test_explicit_configuration_needs_no_tables_or_reference(device, monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('explicit configuration consulted calibration tables')
    monkeypatch.setattr(mf, 'choose_threshold', forbidden)
    monkeypatch.setattr(mf, 'choose_config', forbidden)
    d, h = inputs()
    flat = mf.MatchedFilter(1024, 2, 2, device=device)
    hier = mf.HierarchicalFilter(1024, 2, 2, band=256, device=device)
    hier.set_coarse_threshold(0)
    for f in (flat, hier):
        f.set_data(d)
        f.set_templates(h)
    a, b = flat.run().copy(), hier.run().copy()
    np.testing.assert_array_equal(a['index'], b['index'])
    np.testing.assert_allclose(a['value'], b['value'], rtol=1e-5, atol=1e-4)
    hier.set_coarse_threshold(None)
    with pytest.raises(ValueError, match='no calibrated coarse threshold'):
        hier.run()


def test_explicit_threshold_requires_explicit_band(device):
    f = mf.HierarchicalFilter(1024, device=device)
    with pytest.raises(ValueError, match='explicit band'):
        f.set_coarse_threshold(0)


def test_reference_change_rescales_existing_templates(device):
    d, h = inputs()
    ref = np.ones(1024, np.float32)
    ref[:256] = .02
    def build():
        f = mf.HierarchicalFilter(1024, 2, 2, band=256, device=device)
        f.set_coarse_threshold(100)
        f.set_data(d)
        return f
    changed, fresh = build(), build()
    changed.set_reference(np.ones(1024))
    changed.set_templates(h)
    changed.set_reference(ref)
    fresh.set_reference(ref)
    fresh.set_templates(h)
    a, b = changed.run().copy(), fresh.run().copy()
    np.testing.assert_array_equal(a['index'], b['index'])
    np.testing.assert_allclose(a['value'], b['value'], rtol=1e-5, atol=1e-4)
    assert changed.stats == fresh.stats


@pytest.mark.parametrize('value', [float('nan'), -1., float('inf'), 1e100])
def test_invalid_file_threshold_is_rejected_on_both_devices(device, monkeypatch, value):
    monkeypatch.setattr(mf, 'choose_threshold', lambda *a, **kw: value)
    f = mf.HierarchicalFilter(1024, band=256, device=device)
    f.set_reference(np.ones(1024))
    with pytest.raises(ValueError, match='coarse threshold'):
        f.set_templates(np.ones((1,1024), np.complex64))
        f.set_data(np.ones((1,1024), np.complex64))
        f.run()


def test_explicit_threshold_must_fit_float32(device):
    f = mf.HierarchicalFilter(1024, band=256, device=device)
    with pytest.raises(ValueError, match='float32'):
        f.set_coarse_threshold(1e100)
    assert f._cal_thr is None


def test_budget_below_model_resolution_is_refused():
    assert mf.choose_threshold(np.ones(1024),1024,5.,1e-8,512) is None


@pytest.mark.parametrize('variable', ['MF_ACCURACY', 'MF_THRESHOLD'])
def test_retired_gate_file_overrides_are_not_silently_ignored(monkeypatch, variable):
    monkeypatch.setenv(variable, '/unused/legacy.txt')
    with pytest.raises(ValueError, match=variable + ' is retired'):
        mf.choose_threshold(np.ones(1024), 1024, 5., .01, 512)
