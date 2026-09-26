"""Forward FFT direction, padding, shared ownership and DLPack-only ingestion."""
import gc
import numpy as np
import pytest
import matchedfilter as mf
from conftest import usable_gpu


class Producer:
    """No __array__ or buffer protocol: ingestion must actually use DLPack."""
    def __init__(self, array):
        self.array = array

    def __dlpack_device__(self):
        return self.array.__dlpack_device__()

    def __dlpack__(self, *args, **kwargs):
        return self.array.__dlpack__(*args, **kwargs)


def random_complex(rng, shape):
    return (rng.normal(size=shape) + 1j*rng.normal(size=shape)).astype(np.complex64)


@pytest.fixture
def gpu():
    device = usable_gpu()
    if device is None:
        pytest.skip('no usable GPU')
    return device


@pytest.mark.parametrize('n', sorted(mf._GPU_SIZES))
def test_gpu_forward_matches_reference(gpu, n):
    plan = mf.MatchedFilter(n, device=gpu)
    rng = np.random.default_rng(948)
    series = plan.empty_shared(2*n + 3)
    series[:] = random_complex(rng, series.shape)
    starts = plan.empty_shared(5, np.uint32)
    starts[:] = [0, 7, 2*n, series.size, np.iinfo(np.uint32).max]
    spectra = plan.empty_shared((5, n))
    plan._gpu.forward(n, series, starts, spectra)
    for j, start in enumerate(starts):
        block = np.zeros(n, np.complex64)
        chunk = series[int(start):int(start)+n]
        block[:len(chunk)] = chunk
        expected = np.fft.fft(block) / n
        np.testing.assert_allclose(spectra[j], expected, atol=2e-6, rtol=2e-4)
    # No stale staging values survive an all-zero input.
    series[:] = 0
    plan._gpu.forward(n, series, starts, spectra)
    np.testing.assert_array_equal(spectra, 0)


@pytest.mark.parametrize('kind', ['flat', 'hier'])
@pytest.mark.parametrize('device_name', ['cpu', 'gpu'])
def test_series_has_no_numpy_fft_and_accepts_dlpack(kind, device_name, monkeypatch):
    device = usable_gpu() if device_name == 'gpu' else 'cpu'
    if device is None:
        pytest.skip('no usable GPU')
    n = 1024
    kwargs = dict(device=device)
    if kind == 'hier':
        kwargs['band'] = 256
    cls = mf.MatchedFilter if kind == 'flat' else mf.HierarchicalFilter
    plan = cls(n, 2, 2, **kwargs)
    if kind == 'hier':
        plan.set_coarse_threshold(0.)
    rng = np.random.default_rng(456)
    templates = random_complex(rng, (2, n))
    series = random_complex(rng, 1300)
    starts = np.array([0, 600, 1298, 1300, 2**40], np.uintp)
    lo = np.array([3]*5, np.uintp)
    hi = np.array([999]*5, np.uintp)
    plan.set_templates(Producer(templates))
    plan.set_data(Producer(templates))
    reference = mf.MatchedFilter(n, 2, 2, device='cpu')
    reference.set_templates(templates)
    expected = reference.run_series(series, starts, lo, hi, binsize=200)

    def forbidden(*args, **kwargs):
        raise AssertionError('execution called a NumPy FFT')
    for name in ['fft', 'ifft', 'rfft', 'irfft']:
        monkeypatch.setattr(np.fft, name, forbidden)
    if device_name == 'gpu':
        plan.set_memory_limits(series_bytes=1, cache_bytes=1)
    actual = plan.run_series(*map(Producer, (series, starts, lo, hi)), binsize=200)
    np.testing.assert_array_equal(actual['index'], expected['index'])
    np.testing.assert_allclose(actual['value'], expected['value'], rtol=3e-4, atol=2e-5)


@pytest.mark.parametrize('kind', ['flat', 'hier'])
def test_shared_banks_bind_without_copy_and_survive_eviction(gpu, kind):
    from matchedfilter._shared import shared_buffer
    cls = mf.MatchedFilter if kind == 'flat' else mf.HierarchicalFilter
    kwargs = dict(device=gpu)
    if kind == 'hier':
        kwargs['band'] = 256
    plan = cls(1024, 2, 2, **kwargs)
    if kind == 'hier':
        plan.set_coarse_threshold(0.)
    rng = np.random.default_rng(839)
    data = plan.empty_shared((2, 1024))
    templates = plan.empty_shared((2, 1024))
    data[:] = random_complex(rng, data.shape)
    templates[:] = random_complex(rng, templates.shape)
    plan.set_data(Producer(data))
    plan.set_templates(Producer(templates))
    assert np.shares_memory(plan._gdata, data)
    assert np.shares_memory(plan._gtmpl, templates)
    expected = plan.run().copy()
    batches = plan._gpu._batches if kind == 'flat' else plan._gpu._hier
    batch = next(iter(batches.values()))
    if kind == 'flat':
        bound = batch[:2]
    else:
        bufs = batch[0] if isinstance(batch, tuple) else batch
        bound = [bufs['data'], bufs['tmpl']]
    for array, buf in zip((data, templates), bound):
        assert buf.handle == shared_buffer(array, plan._gpu).handle
    # DLPack's capsule and NumPy base chain must retain the actual allocation.
    view = np.from_dlpack(Producer(data))
    del data
    plan.clear_cache()
    gc.collect()
    np.testing.assert_array_equal(view, plan._gdata)
    actual = plan.run()
    np.testing.assert_array_equal(actual, expected)
    del plan, templates
    gc.collect()
    assert np.isfinite(view).all()


def test_shared_shapes_and_types(gpu):
    plan = mf.MatchedFilter(1024, device=gpu)
    for shape in [(-1,), (2, -3)]:
        with pytest.raises(ValueError):
            plan.empty_shared(shape)
    with pytest.raises(TypeError):
        plan.empty_shared((2,), object)
    assert plan.empty_shared((0, 3)).shape == (0, 3)


def test_shared_series_refresh_and_validation_failure(gpu):
    plan = mf.HierarchicalFilter(1024, 1, 1, band=256, device=gpu)
    rng = np.random.default_rng(129)
    plan.set_templates(random_complex(rng, (1, 1024)))
    series = plan.empty_shared(1200)
    series[:] = random_complex(rng, series.shape)
    args = ([0, 700], [0, 0], [1024, 1024])
    # Failure after preparing a forward command cannot leak into later work.
    with pytest.raises(ValueError):
        plan.run_series(series, *args)
    assert getattr(plan._gpu, '_pending_forward', None) is None
    plan.set_coarse_threshold(0.)
    first = plan.run_series(series, *args).copy()
    assert plan._series_workspace[1] is None  # no redundant source allocation
    series *= np.complex64(2j)
    second = plan.run_series(Producer(series), *args)
    np.testing.assert_array_equal(second['index'], first['index'])
    np.testing.assert_allclose(second['value'], first['value']*2j, rtol=1e-4, atol=2e-5)


def test_shared_bank_replacement_and_external_context(gpu):
    plan = mf.MatchedFilter(1024, device=gpu)
    other = mf.MatchedFilter(1024, device=gpu)
    rng = np.random.default_rng(341)
    plan.set_templates(random_complex(rng, (1, 1024)))
    shared = plan.empty_shared((1, 1024))
    shared[:] = random_complex(rng, shared.shape)
    plan.set_data(shared)
    first = plan.run().copy()
    replacement = plan.empty_shared(shared.shape)
    replacement[:] = shared*2j
    plan.set_data(replacement)
    second = plan.run()
    np.testing.assert_array_equal(second['index'], first['index'])
    np.testing.assert_allclose(second['value'], first['value']*2j, rtol=1e-5, atol=1e-3)
    alien = other.empty_shared(shared.shape)
    alien[:] = shared
    plan.set_data(alien)
    assert not np.shares_memory(plan._gdata, alien)
    np.testing.assert_array_equal(plan.run(), first)


def test_cpu_dlpack_noncontiguous_banks_and_reference():
    rng = np.random.default_rng(145)
    bank = random_complex(rng, (2, 2048))[:, ::2]
    plan = mf.HierarchicalFilter(1024, 2, 2, band=256, device='cpu')
    plan.set_coarse_threshold(0.)
    plan.set_reference(Producer(np.ones(1024, np.float32)))
    plan.set_data(Producer(bank))
    plan.set_templates(Producer(bank))
    expected = mf.MatchedFilter(1024, 2, 2, device='cpu')
    expected.set_data(bank)
    expected.set_templates(bank)
    actual = plan.run()
    reference = expected.run()
    np.testing.assert_array_equal(actual['index'], reference['index'])
    np.testing.assert_allclose(actual['value'], reference['value'], rtol=1e-5)
