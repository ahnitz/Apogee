"""Exercise Vulkan/Metal upload lifetime without requiring a GPU.

Only allocation and submission are replaced: the production dispatch methods
choose the cached buffers and decide which inputs to write.
"""
from types import SimpleNamespace

import numpy as np
import pytest

from matchedfilter import _vkcompute


@pytest.mark.parametrize("layout", ["contiguous", "strided", "reversed", "transposed"])
def test_half_packing_preserves_shader_bit_layout(layout):
    """The shader expects real in bits 0..15, imaginary in bits 16..31."""
    values = np.array([0., -0., 1., -1., 2**-24, 65504., 65520.,
                       np.inf, -np.inf, np.nan], np.float32)
    a = np.empty((4, values.size), np.complex64)
    a.real = values
    a.imag = values[::-1]
    if layout == "strided":
        a = a[:, ::2]
    elif layout == "reversed":
        a = a[:, ::-1]
    elif layout == "transposed":
        a = a.T
    with np.errstate(over="ignore", invalid="ignore"):
        expected = (a.real.astype(np.float16).view(np.uint16).astype(np.uint32)
                    | (a.imag.astype(np.float16).view(np.uint16).astype(np.uint32) << 16))
        got = _vkcompute._pack_half2(a)
    np.testing.assert_array_equal(got, expected)
    assert got.shape == a.shape and got.flags.c_contiguous


def vulkan_gpu():
    from conftest import usable_gpu
    import matchedfilter as mf
    device = usable_gpu()
    if device is None or next(d for d in mf.devices() if str(d) == device).backend != "vulkan":
        pytest.skip("requires a Vulkan GPU")
    return device


class Buffer:
    def __init__(self, *args):
        self.value = None
        self.writes = 0
        self.handle = None

    def destroy(self):
        pass

    def write(self, value):
        self.value = value.copy()
        self.writes += 1

    def read(self, dtype, count):
        return np.zeros(count, dtype=dtype)


@pytest.fixture(params=["vulkan", "metal"])
def ctx(request, monkeypatch):
    from matchedfilter import _mtlcompute
    backend = _vkcompute if request.param == "vulkan" else _mtlcompute
    c = backend.Context.__new__(backend.Context)
    c._test_backend = request.param
    c._batches, c._hier = {}, {}
    c._uploaded = {"data": {}, "tmpl": {}}
    c._pipelines = {}
    c.queue = None
    c.vk = SimpleNamespace(vkQueueSubmit=lambda *args: 0,
                           vkQueueWaitIdle=lambda *args: 0)
    c._make_batch = lambda *args: (*[Buffer() for _ in range(4)], None)
    c._make_hier = lambda *args: (
        {name: Buffer() for name in ("data", "tmpl", "cdata", "ct0",
                                     "idx", "val", "args")}, None)
    if request.param == "metal":
        monkeypatch.setattr(backend, "_Buffer", Buffer)
        c.o = SimpleNamespace(call=lambda *args, **kw: None)
        c.pipeline = lambda *args: None
        c._check_completed = lambda *args: None
        c._record_gpu_time = lambda *args: None
    return c


@pytest.mark.parametrize("hier", [False, True])
@pytest.mark.parametrize("changed", ["data", "tmpl"])
def test_revisited_window_receives_updated_inputs(ctx, hier, changed):
    n = 2048
    data = np.ones((1, n), np.complex64)
    tmpl = np.ones((1, n), np.complex64)

    def run(window, dirty):
        kw = dict(window=window, binsize=n // 2, upload_data=dirty == "data",
                  upload_tmpl=dirty == "tmpl")
        if hier:
            ctx.hier_peaks(n, 1024, data, tmpl, tmpl[:, :1024],
                           0., **kw)
        else:
            ctx.peaks(n, data, tmpl, **kw)

    a, b = (0, n), (100, n // 2)
    run(a, None)
    run(b, None)
    (data if changed == "data" else tmpl)[:] = 7 + 2j
    run(a, changed)
    run(b, None)  # caller has already cleared its dirty flag
    if hier:
        buffers = list(ctx._hier.values())[-1]
        if ctx._test_backend == "vulkan":
            buffers = buffers[0]
        target = buffers[changed]
        if changed == "tmpl":
            coarse = tmpl[:, :1024]
            if (ctx._test_backend == "vulkan" and _vkcompute._use_c16(1024)
                    and not _vkcompute._COARSE_TILE.get(1024)):
                coarse = _vkcompute._pack_half2(coarse)
            np.testing.assert_array_equal(buffers["ct0"].value, coarse)
    else:
        target = list(ctx._batches.values())[-1][0 if changed == "data" else 1]
    np.testing.assert_array_equal(target.value, data if changed == "data" else tmpl)
    writes = target.writes
    run(b, None)
    assert target.writes == writes  # unchanged input still avoids a transfer


@pytest.mark.parametrize("hier", [False, True])
def test_split_dispatch_keeps_resident_inputs(ctx, hier):
    """More bins than fit in one kernel must not invalidate earlier pieces."""
    n = 8192  # three full splits plus a differently sized last piece
    d = np.ones((1, n), np.complex64)
    h = np.ones((1, n), np.complex64)
    def run(dirty):
        kw = dict(binsize=1, window=(17, n), upload_data=dirty,
                  upload_tmpl=dirty)
        if hier:
            ctx.hier_peaks(n, 1024, d, h, h[:, :1024], 0., **kw)
        else:
            ctx.peaks(n, d, h, **kw)
    def input_writes():
        if hier:
            buffers = [(v[0] if ctx._test_backend == "vulkan" else v)
                       for v in ctx._hier.values()]
            return sum(b[name].writes for b in buffers for name in
                       ("data", "tmpl", "cdata", "ct0"))
        return sum(b[0].writes + b[1].writes for b in ctx._batches.values())
    for _ in range(2):
        d *= 2
        h *= 3
        run(True)
        warm = input_writes()
        run(False)
        assert input_writes() == warm, "unchanged split call re-uploaded inputs"


@pytest.mark.parametrize("hier", [False, True])
def test_changing_data_keeps_templates_resident(ctx, hier):
    n = 2048
    d, h = np.ones((1, n), np.complex64), np.ones((1, n), np.complex64)
    def run(dirty):
        kw = dict(upload_data=dirty, upload_tmpl=False)
        if hier:
            ctx.hier_peaks(n, 1024, d, h, h[:, :1024], 0., **kw)
        else:
            ctx.peaks(n, d, h, **kw)
    run(True)
    for _ in range(3):
        d *= 2
        run(True)
    if hier:
        buffers = next(iter(ctx._hier.values()))
        if ctx._test_backend == "vulkan":
            buffers = buffers[0]
        assert all(buffers[name].writes == 1 for name in ("tmpl", "ct0"))
        assert buffers["data"].writes == 4
    else:
        buffers = next(iter(ctx._batches.values()))
        assert buffers[1].writes == 1
        assert buffers[0].writes == 4


@pytest.mark.parametrize("hier", [False, True])
@pytest.mark.parametrize("changed", ["data", "tmpl"])
def test_revisited_window_matches_float64_on_gpu(hier, changed):
    device = vulkan_gpu()
    c = _vkcompute.Context(int(device.split(":")[1]))
    n = 2048
    rng = np.random.default_rng(57)
    def random_spectra():
        return (rng.normal(size=(2, n)) + 1j * rng.normal(size=(2, n))).astype(np.complex64)
    data, tmpl = random_spectra(), random_spectra()
    def run(window, dirty):
        kw = dict(window=window, binsize=n, upload_data=dirty == "data",
                  upload_tmpl=dirty == "tmpl")
        if hier:
            return c.hier_peaks(n, 1024, data, tmpl, tmpl[:, :1024],
                               0., **kw)
        return c.peaks(n, data, tmpl, **kw)
    try:
        run((0, n), None)
        run((100, n), None)
        (data if changed == "data" else tmpl)[:] = random_spectra()
        run((0, n), changed)
        idx, val = run((100, n), None)
        ref = np.fft.ifft(data.astype(np.complex128)[:, None, :]
                          * tmpl.astype(np.complex128).conj()[None, :, :], axis=-1) * n
        expected = np.abs(ref[:, :, 100:]).argmax(axis=-1) + 100
        np.testing.assert_array_equal(idx[:, :, 0], expected)
        np.testing.assert_allclose(val[:, :, 0],
                                   np.take_along_axis(ref, expected[:, :, None], axis=-1)[:, :, 0],
                                   rtol=1e-5, atol=1e-5)
    finally:
        c.destroy()


def test_public_filter_refreshes_cached_windows_and_subranges():
    import matchedfilter as mf
    device = vulkan_gpu()
    rng = np.random.default_rng(81)
    n = 2048
    cpu = mf.MatchedFilter(n, ndata=2, ntemplates=2)
    gpu = mf.MatchedFilter(n, ndata=2, ntemplates=2, device=device)
    for _ in range(2):
        data = (rng.normal(size=(2, n)) + 1j * rng.normal(size=(2, n))).astype(np.complex64)
        tmpl = (rng.normal(size=(2, n)) + 1j * rng.normal(size=(2, n))).astype(np.complex64)
        for plan in (cpu, gpu):
            plan.set_data(data)
            plan.set_templates(tmpl)
        for window in ((0, n), (100, n), (0, n)):
            for start in (0, 1, 0):
                kw = dict(window=window, binsize=n, data=(start, 1), templates=(start, 1))
                want, got = cpu.run(**kw), gpu.run(**kw)
                np.testing.assert_array_equal(got["index"], want["index"])
                np.testing.assert_allclose(got["value"], want["value"], rtol=1e-5, atol=1e-5)
