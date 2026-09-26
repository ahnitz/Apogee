"""Both public entry points bound the work of large GPU correlations."""
import numpy as np
import pytest
import matchedfilter as mf
from conftest import usable_gpu


@pytest.mark.parametrize('kind', ['flat','hier'])
def test_large_transform_splits_before_dispatch(kind, monkeypatch):
    device = usable_gpu()
    if device is None:
        pytest.skip('no usable GPU')
    n, nd, nt = 65536, 17, 512  # one row beyond the large-transform work bound
    cls = mf.MatchedFilter if kind=='flat' else mf.HierarchicalFilter
    f = cls(n, nd, nt, device=device, **({'band':256} if kind=='hier' else {}))
    if kind=='hier':
        f.set_coarse_threshold(0.)  # every pair must refine
    h = np.zeros((nt,n), np.complex64)
    h[:,0] = 1
    f.set_templates(h)
    calls = []
    original = f._gpu_dispatch

    def dispatch(d, h, *args):
        calls.append(d.shape[0]*h.shape[0])
        assert calls[-1] <= f._gpu_pair_limit()
        return original(d, h, *args)

    monkeypatch.setattr(f, '_gpu_dispatch', dispatch)
    try:
        lo, hi = n//4, 3*n//4
        series = np.ones(nd*n, np.complex64)
        result = f.run_series(series, np.arange(nd)*n, [lo]*nd, [hi]*nd)
        np.testing.assert_array_equal(result['value'], 1)
        np.testing.assert_array_equal(result['index'], lo)
        assert len(calls)>1 and sum(calls)==nd*nt
        calls.clear()
        d = np.zeros((nd,n), np.complex64)
        d[:,0] = 1
        f.set_data(d)
        result = f.run(window=(lo,hi))
        np.testing.assert_array_equal(result['value'], 1)
        np.testing.assert_array_equal(result['index'], lo)
        assert len(calls)>1 and sum(calls)==nd*nt
    finally:
        f._gpu.destroy()
