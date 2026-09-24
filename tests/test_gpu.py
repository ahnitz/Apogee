"""End-to-end filtering on every device, through the public API.

This file once drove a slangpy development spike. That made it skip wherever
slangpy was absent -- which is most environments, including this project's
own -- so it reported "no GPU path" on a machine with a working GPU. It also
could not reach binsize or window, because those live in run() and the spike
only ever returned a peak magnitude.

Everything here goes through matchedfilter.MatchedFilter, so the GPU is held
to the same standard as the CPU by the same assertions.
"""
import numpy as np
import pytest

import matchedfilter as mf

TIER_B = (1024, 2048, 4096, 8192, 16384)


def devices():
    """cpu, plus a GPU this machine can actually run -- see conftest.

    Enumeration is not availability: a driver that cannot allocate its shared
    memory still lists the adapter, and gating on the list alone turns a
    broken driver into failures that read like defects here.
    """
    from conftest import usable_gpu
    out = ["cpu"]
    g = usable_gpu()
    if g:
        out.append(g)
    return out


DEVICES = devices()


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


def build(device, n, nd, nt):
    f = mf.MatchedFilter(n, ndata=nd, ntemplates=nt, device=device)
    return f


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("n", TIER_B)
def test_peak_matches_a_float64_reference(device, n):
    """Every supported length, against the same reference on every device."""
    d, h = spectra(n, 3, 5, seed=n)
    f = build(device, n, 3, 5)
    f.set_data(d)
    f.set_templates(h)
    pk = f.run(binsize=n, threshold=0.0)
    assert pk.shape == (3, 5, 1)
    want = reference_peaks(d, h)
    got = np.abs(pk["value"][:, :, 0])
    assert np.max(np.abs(got - want) / want) < 1e-5


@pytest.mark.parametrize("device", DEVICES)
def test_finds_an_injected_signal_at_the_right_lag(device):
    """A peak that is a real peak, not a noise excursion.

    The lag is asserted, not just the height: a transform that is right in
    magnitude and wrong in ordering passes a magnitude check and fails here.
    """
    n, lag, snr = 4096, 1301, 9.0
    d, h = spectra(n, 4, 16, seed=3)
    ramp = np.exp(-2j * np.pi * lag * np.arange(n) / n)
    d[2] += (snr * h[7] * ramp).astype(np.complex64)

    f = build(device, n, 4, 16)
    f.set_data(d)
    f.set_templates(h)
    pk = f.run(binsize=n, threshold=0.0)

    mag = np.abs(pk["value"][:, :, 0])
    di, ti = np.unravel_index(int(np.argmax(mag)), mag.shape)
    assert (di, ti) == (2, 7), "the injection should be the loudest pair"
    assert int(pk["index"][2, 7, 0]) == lag


@pytest.mark.parametrize("device", DEVICES)
def test_large_batch(device):
    """32768 pairs -- the shape a real call has, on every device.

    Small batches cannot expose anything that depends on having many
    workgroups in flight, and this is also an ordinary size for the CPU:
    it costs the CPU backend about 0.12s.
    """
    n, nd, nt = 4096, 64, 512
    d, h = spectra(n, nd, nt, seed=5)
    f = build(device, n, nd, nt)
    f.set_data(d)
    f.set_templates(h)
    pk = f.run(binsize=n, threshold=0.0)
    assert pk.shape == (nd, nt, 1)

    pairs = [(0, 0), (3, 31), (17, 255), (63, 511)]
    want = reference_peaks(np.array([d[i] for i, _ in pairs]),
                           np.array([h[j] for _, j in pairs]))
    for k, (i, j) in enumerate(pairs):
        rel = abs(np.abs(pk["value"])[i, j, 0] - want[k, k]) / want[k, k]
        assert rel < 1e-4, "pair (%d,%d): %.2e" % (i, j, rel)


@pytest.mark.parametrize("n", TIER_B)
def test_cpu_and_gpu_agree_pair_for_pair(n):
    """The two backends on the same input, compared to each other.

    Stronger than each against its own reference: it catches anything that
    is consistently wrong in one backend, and it is the only check that the
    index conventions really coincide.
    """
    gpus = [d for d in DEVICES if d != "cpu"]
    if not gpus:
        from matchedfilter import _vulkan
        pytest.skip(_vulkan.available()[1] or "no usable GPU")
    nd, nt, binsize = 3, 5, n // 8
    d, h = spectra(n, nd, nt, seed=n + 1)

    out = {}
    for device in ("cpu", gpus[0]):
        f = build(device, n, nd, nt)
        f.set_data(d)
        f.set_templates(h)
        out[device] = f.run(binsize=binsize, threshold=1.0).copy()

    a, b = out["cpu"], out[gpus[0]]
    assert a.shape == b.shape
    assert np.array_equal(a["index"] >= 0, b["index"] >= 0)
    live = a["index"] >= 0
    # An index may legitimately differ only where the magnitudes tie; float32
    # summation order differs between the backends, so compare values, and
    # require the indices to match everywhere the values are not a tie.
    np.testing.assert_allclose(np.abs(a["value"][live]), np.abs(b["value"][live]),
                               rtol=2e-4, atol=2e-4)
    moved = a["index"][live] != b["index"][live]
    if moved.any():
        am = np.abs(a["value"][live])[moved]
        bm = np.abs(b["value"][live])[moved]
        assert np.allclose(am, bm, rtol=1e-4), "an index moved where the value did not tie"


def test_absent_gpu_is_explained():
    """A machine with no GPU must say why, or it looks like a pass.

    The common cause here is not an absent GPU at all: a conda prefix early
    on the library path supplies an older libstdc++ than the Mesa drivers
    need, every ICD fails to load, and the loader reports no devices.
    """
    from matchedfilter import _vulkan
    ok, reason = _vulkan.available()
    assert ok or (reason and len(reason) > 10), reason
