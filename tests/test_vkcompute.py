"""The Vulkan dispatch path, driven without slangpy.

These run wherever a Vulkan device exists, including a software one, which
is the point: they cover the host code -- descriptor layout, push constants,
memory type selection, dispatch shape -- on a CI runner with no GPU.  What
they do not cover is performance, and a software device would give a
misleading number, so nothing here times anything.
"""
import numpy as np
import pytest

from matchedfilter import _vulkan

_devices, _reason = _vulkan.enumerate_devices()
novk = pytest.mark.skipif(not _devices, reason=_reason or "no Vulkan device")

TIER_B = (1024, 2048, 4096, 8192, 16384)


def spectra(n, nd, nt, seed=0):
    rng = np.random.default_rng(seed)
    d = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    h = (rng.standard_normal((nt, n)) + 1j * rng.standard_normal((nt, n))).astype(np.complex64)
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    return d, h


def reference_peaks(d, h):
    """max |ifft(D * conj(H)) * n|, in float64."""
    n = d.shape[1]
    return np.abs(np.fft.ifft(d[:, None, :].astype(np.complex128)
                              * np.conj(h)[None, :, :].astype(np.complex128),
                              axis=2) * n).max(axis=2)


@pytest.fixture(scope="module")
def ctx():
    from matchedfilter import _vkcompute
    c = _vkcompute.Context(0)
    yield c
    c.destroy()


@novk
@pytest.mark.parametrize("n", TIER_B)
def test_peak_matches_a_float64_reference(ctx, n):
    """Every shipped blob, dispatched by the shipped host code.

    float32 accumulation over an n-point transform lands near 2e-7 relative;
    1e-5 is loose enough not to be flaky and far tighter than any of the
    structural bugs this has caught, which were wrong by 15% or more.
    """
    d, h = spectra(n, 3, 5, seed=n)
    got = ctx.peaks(n, d, h)
    want = reference_peaks(d, h)
    assert got.shape == (3, 5)
    assert np.max(np.abs(got - want) / want) < 1e-5


@novk
def test_pipeline_is_cached():
    """Pipeline creation compiles SPIR-V in the driver and costs milliseconds.

    A batched caller dispatches many times per plan, so rebuilding per call
    would cost more than the work.
    """
    from matchedfilter import _vkcompute
    c = _vkcompute.Context(0)
    try:
        first = c.pipeline(1024)
        assert c.pipeline(1024) is first
        assert c.pipeline(2048) is not first
    finally:
        c.destroy()


@novk
def test_gpu_shaped_batch(ctx):
    """32768 pairs -- the shape a real call has, and the CPU test's shape.

    Small batches cannot expose anything that depends on having many
    workgroups in flight.
    """
    n, nd, nt = 4096, 64, 512
    d, h = spectra(n, nd, nt, seed=11)
    got = ctx.peaks(n, d, h)
    assert got.shape == (nd, nt)
    assert np.all(np.isfinite(got)) and np.all(got > 0)

    idx = [(0, 0), (17, 255), (63, 511)]
    want = reference_peaks(np.array([d[i] for i, _ in idx]),
                           np.array([h[j] for _, j in idx]))
    for k, (i, j) in enumerate(idx):
        assert abs(got[i, j] - want[k, k]) / want[k, k] < 1e-5


@novk
def test_rectangular_batches_are_not_transposed(ctx):
    """nd != nt, so a swapped index would survive a square test.

    ntmpl arrives as a push constant rather than a descriptor; getting that
    wrong indexes the output with the wrong stride and is invisible when the
    two dimensions match.
    """
    n, nd, nt = 1024, 3, 7
    d, h = spectra(n, nd, nt, seed=4)
    got = ctx.peaks(n, d, h)
    assert got.shape == (nd, nt)
    assert np.max(np.abs(got - reference_peaks(d, h)) / reference_peaks(d, h)) < 1e-5
