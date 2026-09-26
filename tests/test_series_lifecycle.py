"""State transitions and boundary inputs, across both filter classes/devices."""
import numpy as np
import pytest

import matchedfilter as mf
from conftest import usable_gpu


@pytest.fixture(params=["cpu", "gpu"])
def device(request):
    if request.param == "cpu":
        return "cpu"
    value = usable_gpu()
    if value is None:
        pytest.skip("no usable GPU")
    return value


@pytest.fixture(params=["flat", "hier"])
def plan(device, request):
    n = 2048
    if request.param == "flat":
        f = mf.MatchedFilter(n, ndata=2, ntemplates=2, device=device)
    else:
        f = mf.HierarchicalFilter(n, ndata=2, ntemplates=2, band=512,
                                  snr=5.5, fd=1e-2, device=device)
        f.set_reference(np.ones(n, np.float32))
        f.set_coarse_threshold(0.)  # isolate execution from statistical gating
    rng = np.random.default_rng(441)
    h = (rng.normal(size=(2, n)) + 1j * rng.normal(size=(2, n))).astype(np.complex64)
    f.set_templates(h)
    return f


def test_reused_series_staging_is_uploaded(plan, monkeypatch):
    """Force allocator reuse: same address and shape, different series values."""
    n = plan.n
    rng = np.random.default_rng(711)
    scratch = np.empty((2, n), np.complex64)
    contiguous = np.ascontiguousarray
    def recycled(a, *args, **kwargs):
        result = contiguous(a, *args, **kwargs)
        if result.shape == scratch.shape and result.dtype == scratch.dtype:
            scratch[:] = result
            return scratch
        return result
    monkeypatch.setattr(np, "ascontiguousarray", recycled)
    series = (rng.normal(size=2*n) + 1j*rng.normal(size=2*n)).astype(np.complex64)
    kw = dict(starts=[0, n], win_start=[0, 0], win_end=[n, n],
              binsize=n, threshold=0.)
    first = plan.run_series(series, **kw).copy()
    second = plan.run_series(series * np.complex64(2j), **kw).copy()
    assert (first["index"] >= 0).all()
    np.testing.assert_array_equal(second["index"], first["index"])
    np.testing.assert_allclose(second["value"], first["value"] * 2j,
                               rtol=1e-5, atol=1e-5)


def test_empty_series_and_padded_tail_are_zero(plan):
    n = plan.n
    for series, starts in ((np.empty(0, np.complex64), [0, 3]),
                           (np.ones(3, np.complex64), [3, 7])):
        peaks = plan.run_series(series, starts, [0, 0], [n, n], binsize=n)
        np.testing.assert_array_equal(peaks["index"], -1)
        np.testing.assert_array_equal(peaks["value"], 0.)


@pytest.mark.parametrize("windows", [[0, 0, 37, 37], [0, 37, 0, 37]])
def test_series_window_groups_preserve_block_order(plan, windows):
    """Both contiguous groups and interleaved groups match independent blocks."""
    n = plan.n
    rng = np.random.default_rng(773)
    series = (rng.normal(size=4*n) + 1j*rng.normal(size=4*n)).astype(np.complex64)
    starts = np.arange(4) * n
    got = plan.run_series(series, starts, windows, [n]*4, binsize=n).copy()
    assert (got["index"] >= 0).all()
    for b in range(4):
        one = plan.run_series(series, [starts[b]], [windows[b]], [n], binsize=n)
        np.testing.assert_array_equal(got["index"][b], one["index"][0])
        np.testing.assert_allclose(got["value"][b], one["value"][0], rtol=1e-5, atol=1e-5)


@pytest.mark.parametrize("case", ["no_blocks", "series_2d", "starts_2d",
                                  "window_2d", "negative_start", "huge_start",
                                  "empty_templates", "past_templates",
                                  "zero_binsize", "negative_binsize"])
def test_invalid_series_layout_fails_clearly(plan, case, monkeypatch):
    n = plan.n
    kw = dict(series=np.ones(n, np.complex64), starts=np.array([0]),
              win_start=np.array([0]), win_end=np.array([n]), binsize=n)
    if case == "no_blocks":
        kw.update(starts=[], win_start=[], win_end=[])
    elif case == "series_2d":
        kw["series"] = kw["series"].reshape(2, n // 2)
    elif case == "starts_2d":
        kw["starts"] = np.array([[0]])
    elif case == "window_2d":
        kw["win_end"] = np.array([[n]])
    elif case == "negative_start":
        kw["starts"] = np.array([-1], dtype=np.int64)
    elif case == "huge_start":
        kw["starts"] = np.array([np.iinfo(np.uintp).max], dtype=np.uintp)
    elif case == "empty_templates":
        kw["templates"] = (0, 0)
    elif case == "past_templates":
        kw["templates"] = (1, 2)
    else:
        kw["binsize"] = 0 if case == "zero_binsize" else -1
    # A malformed 2-D series originally reached memcpy and crashed Python.
    # Guard the native boundary so a regression fails this test without
    # taking down the whole test process.
    def native_boundary(*args, **kwargs):
        pytest.fail("invalid series layout reached the native backend")
    monkeypatch.setattr(plan, "_ensure", native_boundary)
    monkeypatch.setattr(plan, "_run_series_gpu", native_boundary)
    with pytest.raises(ValueError):
        plan.run_series(**kw)


def test_reference_update_recalibrates_a_reused_gpu_filter():
    device = usable_gpu()
    if device is None:
        pytest.skip("no usable GPU")
    n, band = 2048, 512
    f = mf.HierarchicalFilter(n, band=band, snr=5.5, fd=1e-2, device=device)
    # The coarse peak is 0.5 at f=1/4 and 0.293 at f=8/11. A threshold
    # between those proves recalibration changes the executed gate too.
    f.set_coarse_threshold(.35)
    h = np.full((1, n), 1. / np.sqrt(n), np.complex64)
    d = h.copy()
    d[:, band:] = 0
    f.set_templates(h)
    f.set_data(d)
    for low_power in (1., 8., 1.):
        ref = np.ones(n, np.float32)
        ref[:band] = low_power
        f.set_reference(ref)
        peaks = f.run(binsize=n)
        assert (peaks["index"] >= 0).all() == (low_power == 1.)
        fraction = ref[:band].sum() / ref.sum()
        assert f._gpu_calibration(0.)[1] == pytest.approx(fraction)
        np.testing.assert_allclose(f._ct, h[:, :band] / np.sqrt(fraction), rtol=1e-6)


def test_series_keeps_unchanged_template_buffers_resident(plan, monkeypatch):
    if plan._gpu is None:
        pytest.skip("GPU input transfer contract")
    n = plan.n
    kw = dict(starts=[0, n], win_start=[0, 0], win_end=[n, n], binsize=n)
    plan.run_series(np.ones(2*n, np.complex64), **kw)
    ctx = plan._gpu
    protected = set()
    for batch in ctx._batches.values():
        protected.add(id(batch[1]))
    for batch in ctx._hier.values():
        bufs = batch[0] if plan.device.backend == "vulkan" else batch
        protected.update(id(bufs[name]) for name in ("tmpl", "ct0"))
    assert protected
    buffer_class = plan._backend()._Buffer
    write = buffer_class.write
    calls = []
    def record(buffer, array):
        if id(buffer) in protected:
            calls.append(array.nbytes)
        return write(buffer, array)
    monkeypatch.setattr(buffer_class, "write", record)
    plan.run_series(np.full(2*n, 2j, np.complex64), **kw)
    assert not calls, "a new data series re-uploaded the unchanged template bank"
