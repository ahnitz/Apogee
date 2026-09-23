"""The GPU kernels, held to the same standard as the CPU ones.

These skip -- with the reason -- when there is no Vulkan device, no
driver, or no toolchain, which is most machines and most of CI. Where a
device exists they check the kernels against the SAME float64 reference
the CPU tests use, because that pairing is what caught every silent GPU
bug so far: a gather/scatter race, a wave-width assumption, a buffer
overrun and a transposed axis, none of which would have failed a
benchmark.

CI can run these without a GPU at all. Lavapipe is a software Vulkan
implementation, far too slow to benchmark and entirely adequate to prove
correctness, and the runner falls back to it.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gpu"))

try:
    import runner as gpurun
    _OK, _WHY = gpurun.available()
except Exception as e:                                   # pragma: no cover
    _OK, _WHY = False, "%s: %s" % (type(e).__name__, e)

gpu = pytest.mark.skipif(not _OK, reason="no GPU path (%s)" % _WHY)

#: Lavapipe and llvmpipe are software Vulkan: right for correctness in CI,
#: far too slow for a batch sized to saturate real hardware. Marked rather
#: than deselected by hand, so the suite needs no special invocation.
_SOFTWARE = _OK and any(k in _WHY.lower() for k in ("llvmpipe", "lavapipe", "swiftshader"))
big = pytest.mark.skipif(_SOFTWARE, reason="software rasteriser (%s)" % _WHY)

#: Lengths one workgroup can carry. 32768 and up need the four-step across
#: dispatches and are not implemented; see docs/plans/gpu-integration.md.
TIER_B = (1024, 2048, 4096, 8192, 16384)


def spectra(n, nd, nt, seed=0):
    rng = np.random.default_rng(seed)
    d = (rng.standard_normal((nd, n)) + 1j*rng.standard_normal((nd, n))).astype(np.complex64)
    h = (rng.standard_normal((nt, n)) + 1j*rng.standard_normal((nt, n))).astype(np.complex64)
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    return d, h


def reference_peaks(d, h):
    """max |ifft(D * conj(H)) * n|, in float64."""
    n = d.shape[1]
    return np.abs(np.fft.ifft(d[:, None, :].astype(np.complex128)
                              * np.conj(h)[None, :, :].astype(np.complex128),
                              axis=2) * n).max(axis=2)


@pytest.fixture(scope="module")
def dev():
    return gpurun.device()


@gpu
@pytest.mark.parametrize("n", TIER_B)
def test_peak_matches_a_float64_reference(dev, n):
    """Every supported length, against the same reference the CPU uses."""
    d, h = spectra(n, 4, 16)
    got = gpurun.peaks(dev, n, d, h)
    want = reference_peaks(d, h)
    rel = np.abs(got - want) / np.maximum(want, 1e-30)
    assert rel.max() < 1e-5, "n=%d: max relative error %.2e" % (n, rel.max())


@gpu
def test_finds_an_injected_signal_at_the_right_lag(dev):
    """A peak that is a real peak, not a noise excursion."""
    n, lag, snr = 4096, 1301, 9.0
    d, h = spectra(n, 4, 16, seed=3)
    ramp = np.exp(-2j*np.pi*lag*np.arange(n)/n)
    d[2] += (snr * h[7] * ramp).astype(np.complex64)
    got = gpurun.peaks(dev, n, d, h)
    want = reference_peaks(d, h)
    di, ti = np.unravel_index(np.argmax(want), want.shape)
    assert (di, ti) == (2, 7), "the injection should be the loudest pair"
    assert abs(got[2, 7] - want[2, 7]) / want[2, 7] < 1e-5


@gpu
@big
def test_large_batch(dev):
    """The shape a GPU is actually given.

    A GPU saturates at roughly 400 pairs per compute unit, so real calls
    hand over tens of thousands of pairs at once -- the pycbc FIR search
    reports about 100k per segment. Small batches hide anything that
    depends on having many workgroups in flight, and the hierarchical
    filter measured 3x SLOWER than flat at 512 pairs purely because 128
    workgroups cannot fill 40 CUs.
    """
    n, nd, nt = 4096, 64, 512                  # 32768 pairs
    d, h = spectra(n, nd, nt, seed=11)
    got = gpurun.peaks(dev, n, d, h)
    assert got.shape == (nd, nt)
    # check a sample against float64 rather than all 32768, which would
    # dominate the suite's runtime
    idx = [(0, 0), (1, 7), (17, 255), (63, 511), (32, 128)]
    sub_d = np.array([d[i] for i, _ in idx])
    sub_h = np.array([h[j] for _, j in idx])
    want = reference_peaks(sub_d, sub_h)
    for k, (i, j) in enumerate(idx):
        rel = abs(got[i, j] - want[k, k]) / want[k, k]
        assert rel < 1e-5, "pair (%d,%d): %.2e" % (i, j, rel)
    assert np.isfinite(got).all() and (got > 0).all()


def test_cpu_large_batch():
    """The SAME shape on the CPU, which must also cope with it.

    Not skipped: this runs everywhere. A batch sized for a GPU is not a
    GPU-only shape -- 32768 pairs at n=4096 costs the CPU backend 0.12s,
    so it is an ordinary call, and matching the GPU test's shape exactly
    makes the two directly comparable instead of merely adjacent.

    It also exercises the plan and buffer paths at a size no other test in
    the suite reaches.
    """
    import matchedfilter as mf
    n, nd, nt = 4096, 64, 512                  # 32768 pairs
    d, h = spectra(n, nd, nt, seed=5)
    filt = mf.MatchedFilter(n, ndata=nd, ntemplates=nt)
    filt.set_data(d)
    filt.set_templates(h)
    peaks = filt.run(binsize=n, threshold=0.0)
    assert peaks.shape == (nd, nt, 1)
    idx = [(0, 0), (3, 31), (17, 255), (63, 511)]
    sub_d = np.array([d[i] for i, _ in idx])
    sub_h = np.array([h[j] for _, j in idx])
    want = reference_peaks(sub_d, sub_h)
    for k, (i, j) in enumerate(idx):
        rel = abs(peaks["magnitude"][i, j, 0] - want[k, k]) / want[k, k]
        assert rel < 1e-4, "pair (%d,%d): %.2e" % (i, j, rel)


def test_gpu_skip_reason_is_reported():
    """A skip must say why, or an absent backend looks like a pass."""
    ok, why = (_OK, _WHY)
    assert isinstance(why, str) and why, "the runner must give a reason"
    if not ok:
        assert ("slangpy" in why or "Vulkan" in why or "device" in why), why
