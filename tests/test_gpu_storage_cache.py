"""Storage reuse must not let command recordings retain stale input state."""
import numpy as np
import pytest
import matchedfilter as mf
from conftest import usable_gpu


@pytest.fixture(params=[('flat',False), ('hier',False), ('flat',True), ('hier',True)])
def plan(request):
    device = usable_gpu()
    if device is None:
        pytest.skip('no usable GPU')
    kind, shared = request.param
    cls = mf.MatchedFilter if kind == 'flat' else mf.HierarchicalFilter
    f = cls(1024, 2, 3, device=device, **({'band':256} if kind=='hier' else {}))
    if kind == 'hier':
        f.set_coarse_threshold(0.)
    assert f._gdata is None and f._gtmpl is None
    rng = np.random.default_rng(1203)
    for setter, shape in ((f.set_data,(2,1024)), (f.set_templates,(3,1024))):
        a = f.empty_shared(shape) if shared else np.empty(shape, np.complex64)
        a[:] = rng.normal(size=shape)+1j*rng.normal(size=shape)
        setter(a)
    return f


def check(a, b):
    np.testing.assert_array_equal(a['index'], b['index'])
    np.testing.assert_allclose(a['value'], b['value'], rtol=3e-5, atol=3e-5)


def test_window_records_share_storage_and_refresh_inputs(plan):
    ctx = plan._gpu
    for offset in range(6):
        plan.run(window=(offset, 1000), binsize=1024)
    if hasattr(ctx, '_storage'):
        assert len(ctx._storage) == 1
        records = ctx._batches or ctx._hier
        assert len(records) == 6
    allocations = {id(ctx._allocation(b)):ctx._allocation(b).nbytes
                   for b in ctx._cached_buffers()}
    assert ctx._cache_bytes() == sum(allocations.values())
    plan._gdata[:] *= 2j
    plan.set_data(plan._gdata)
    plan._gtmpl[:] *= .5j
    plan.set_templates(plan._gtmpl)
    # Refresh one recording, then revisit another recording sharing storage.
    plan.run(window=(1, 1000))
    actual = plan.run(window=(0,1000), raw=True)
    assert actual[0].flags.c_contiguous and actual[1].flags.c_contiguous
    actual = plan.run(window=(0,1000)).copy()
    plan.clear_cache()
    check(actual, plan.run(window=(0,1000)))


def test_selective_record_eviction_preserves_hot_storage(plan):
    ctx = plan._gpu
    if not hasattr(ctx, '_storage'):
        pytest.skip('Vulkan command recording cache')
    ctx.cache_limit_recordings = 3
    expected = plan.run(window=(0,1000)).copy()
    original = next(iter(ctx._storage.values()))
    for lo in range(1,12):
        plan.run(window=(lo,1000))
        assert len(ctx._cache_order) <= 3
        assert len(ctx._storage) == 1
        assert next(iter(ctx._storage.values())) is original
        assert len(ctx._record_pools) <= 3
    check(expected, plan.run(window=(0,1000)))
    plan.clear_cache()
    assert not ctx._storage and not ctx._record_pools and not ctx._cache_order


def test_series_source_capacity_does_not_reallocate_fft_workspace(plan):
    series = np.ones(4096, dtype='complex64')
    plan.run_series(series, [0,512], [0,0], [1024,1024])
    first = plan._series_workspace
    actual = plan.run_series(series[:3000], [0,2700], [0,0], [1024,1024]).copy()
    second = plan._series_workspace
    assert first[1] is second[1] and first[2] is second[2] and first[3] is second[3]
    plan.clear_cache()
    check(actual, plan.run_series(series[:3000], [0,2700], [0,0], [1024,1024]))


def test_raw_counts_accept_numpy_boolean(plan):
    (idx, val), counts = plan.run(raw=True, counts=np.bool_(True))
    assert idx.flags.c_contiguous and val.flags.c_contiguous
    np.testing.assert_array_equal(counts, (idx >= 0).sum(axis=-1))


def test_storage_shape_cap_preserves_recent_shape(plan):
    ctx = plan._gpu
    if not hasattr(ctx, '_storage'):
        pytest.skip('Vulkan storage shape cache')
    ctx.cache_limit_entries = 2
    plan.run(templates=(0,1))
    plan.run(templates=(0,2))
    hot_key = next(reversed(ctx._storage))
    hot_storage = ctx._storage[hot_key]
    plan.run(templates=(0,3))
    assert len(ctx._storage) == 2
    assert ctx._storage[hot_key] is hot_storage
    actual = plan.run(templates=(0,2)).copy()
    plan.clear_cache()
    check(actual, plan.run(templates=(0,2)))


@pytest.mark.parametrize('limit', [2, 3])
def test_run_and_series_share_pair_limit(plan, limit):
    rng = np.random.default_rng(14)
    series = (rng.normal(size=3000)+1j*rng.normal(size=3000)).astype('complex64')
    expected_run = plan.run(binsize=128).copy()
    expected_series = plan.run_series(series,[0,512],[0,0],[1024,1024],binsize=128).copy()
    plan.set_data(plan._gdata)
    plan._gpu.max_dispatch_x = limit  # force data and template splits on small cases
    actual, counts = plan.run(binsize=128, counts=True)
    check(expected_run, actual)
    np.testing.assert_array_equal(counts, (actual['index']>=0).sum(axis=-1))
    check(expected_series, plan.run_series(series,[0,512],[0,0],[1024,1024],binsize=128))
