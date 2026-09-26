"""Eviction and bounded series batches preserve GPU results and state."""
import numpy as np
import pytest
import matchedfilter as mf
from conftest import usable_gpu


@pytest.fixture(params=['flat','hier'])
def plan(request):
    dev=usable_gpu()
    if dev is None: pytest.skip('no usable GPU')
    if request.param=='flat': f=mf.MatchedFilter(1024,2,2,device=dev)
    else:
        f=mf.HierarchicalFilter(1024,2,2,band=256,device=dev)
        f.set_reference(np.ones(1024,np.float32)); f.set_coarse_threshold(0.)
    rng=np.random.default_rng(888)
    h=(rng.normal(size=(2,1024))+1j*rng.normal(size=(2,1024))).astype(np.complex64)
    f.set_templates(h); f.set_data(h)
    return f


def test_cache_eviction_and_explicit_clear(plan):
    expected=plan.run(binsize=1).copy()
    plan.set_memory_limits(cache_bytes=1)
    for threshold in (0.,.1,0.):
        actual=plan.run(binsize=1,threshold=threshold)
        np.testing.assert_array_equal(actual['index'],expected['index'])
        np.testing.assert_allclose(actual['value'],expected['value'],rtol=1e-5,atol=1e-4)
        assert len(plan._gpu._batches)+len(plan._gpu._hier)==1
    plan.clear_cache()
    assert not plan._gpu._batches and not plan._gpu._hier
    actual=plan.run(binsize=1)
    np.testing.assert_array_equal(actual['index'],expected['index'])


def test_series_chunking_and_ragged_windows(plan):
    rng=np.random.default_rng(444)
    ser=(rng.normal(size=4000)+1j*rng.normal(size=4000)).astype(np.complex64)
    args=(ser,[0,300,700,1300,2500,3700],[0,7,0,7,0,7],[1000]*6)
    expected=plan.run_series(*args,binsize=1024).copy()
    plan.set_memory_limits(series_bytes=1,cache_bytes=1)
    actual=plan.run_series(*args,binsize=1024)
    np.testing.assert_array_equal(actual['index'],expected['index'])
    np.testing.assert_allclose(actual['value'],expected['value'],rtol=1e-5,atol=1e-4)
