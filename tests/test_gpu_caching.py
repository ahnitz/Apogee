"""Caching on the GPU path: does a changed input actually reach the device?

Two optimisations landed that are silently wrong if they are wrong, and
neither had a test:

  * uploads are skipped when the data and templates have not changed, so a
    stale buffer would be filtered instead of the new one;
  * buffers, descriptor sets and the recorded COMMAND BUFFER are cached per
    shape, and the push constants are baked into that recording -- so a key
    that forgets a parameter replays the previous call's threshold, window
    or binsize.

Both return entirely plausible peaks when broken. Nothing in the accuracy
suite would notice, because every one of its calls would be internally
consistent; only a second call with different inputs shows it.
"""
import numpy as np
import pytest

import matchedfilter as mf

from test_api import inspiral_power, template_with_power, noise


def gpu_device():
    for d in mf.devices():
        if d.kind == "gpu" and not d.is_software:
            return str(d)
    return None


DEVICE = gpu_device()
pytestmark = pytest.mark.skipif(DEVICE is None, reason="no GPU on this machine")

N, ND, NT = 4096, 3, 8


def spectra(seed):
    rng = np.random.default_rng(seed)
    d = (rng.standard_normal((ND, N)) + 1j * rng.standard_normal((ND, N))).astype(np.complex64)
    h = (rng.standard_normal((NT, N)) + 1j * rng.standard_normal((NT, N))).astype(np.complex64)
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    return d, h


def test_changing_the_data_changes_the_answer():
    """Upload gating must not serve the previous call's data."""
    d1, h = spectra(1)
    d2, _ = spectra(2)
    f = mf.MatchedFilter(N, ND, NT, device=DEVICE)
    f.set_templates(h)
    f.set_data(d1)
    a = f.run(binsize=N, threshold=0.0).copy()
    f.set_data(d2)
    b = f.run(binsize=N, threshold=0.0).copy()
    assert not np.array_equal(a["index"], b["index"]), \
        "new data produced the previous answer: the upload was skipped"


def test_changing_the_templates_changes_the_answer():
    d, h1 = spectra(1)
    _, h2 = spectra(3)
    f = mf.MatchedFilter(N, ND, NT, device=DEVICE)
    f.set_data(d)
    f.set_templates(h1)
    a = f.run(binsize=N, threshold=0.0).copy()
    f.set_templates(h2)
    b = f.run(binsize=N, threshold=0.0).copy()
    assert not np.array_equal(a["value"], b["value"]), \
        "new templates produced the previous answer"


def test_a_run_matches_a_fresh_filter():
    """The cached second call must equal what an untouched filter produces."""
    d1, h = spectra(1)
    d2, _ = spectra(2)
    f = mf.MatchedFilter(N, ND, NT, device=DEVICE)
    f.set_templates(h)
    f.set_data(d1)
    f.run(binsize=N, threshold=0.0)
    f.set_data(d2)
    cached = f.run(binsize=N, threshold=0.0).copy()

    g = mf.MatchedFilter(N, ND, NT, device=DEVICE)
    g.set_templates(h)
    g.set_data(d2)
    fresh = g.run(binsize=N, threshold=0.0)
    np.testing.assert_array_equal(cached["index"], fresh["index"])
    np.testing.assert_allclose(np.abs(cached["value"]), np.abs(fresh["value"]),
                               rtol=1e-6, atol=1e-6)


@pytest.mark.parametrize("a,b", [(0.0, 5.0), (5.0, 50.0), (2.0, 0.0)])
def test_changing_the_threshold_is_not_replayed_from_cache(a, b):
    """The threshold is RECORDED into the command buffer, not passed per call."""
    d, h = spectra(4)
    f = mf.MatchedFilter(N, ND, NT, device=DEVICE)
    f.set_data(d)
    f.set_templates(h)
    first = f.run(binsize=N, threshold=a).copy()
    second = f.run(binsize=N, threshold=b).copy()

    g = mf.MatchedFilter(N, ND, NT, device=DEVICE)
    g.set_data(d)
    g.set_templates(h)
    want = g.run(binsize=N, threshold=b)
    np.testing.assert_array_equal(second["index"], want["index"]), 
    if a != b:
        assert not np.array_equal(first["index"], second["index"]) or \
            np.array_equal(first["index"], want["index"])


@pytest.mark.parametrize("w1,w2", [((0, N), (100, 3000)), ((37, 1000), (0, N))])
def test_changing_the_window_is_not_replayed_from_cache(w1, w2):
    d, h = spectra(5)
    f = mf.MatchedFilter(N, ND, NT, device=DEVICE)
    f.set_data(d)
    f.set_templates(h)
    f.run(binsize=256, threshold=0.0, window=w1)
    got = f.run(binsize=256, threshold=0.0, window=w2).copy()

    g = mf.MatchedFilter(N, ND, NT, device=DEVICE)
    g.set_data(d)
    g.set_templates(h)
    want = g.run(binsize=256, threshold=0.0, window=w2)
    assert got.shape == want.shape
    np.testing.assert_array_equal(got["index"], want["index"])


def test_changing_the_binsize_is_not_replayed_from_cache():
    d, h = spectra(6)
    f = mf.MatchedFilter(N, ND, NT, device=DEVICE)
    f.set_data(d)
    f.set_templates(h)
    f.run(binsize=N, threshold=0.0)
    got = f.run(binsize=512, threshold=0.0).copy()
    assert got.shape[2] == N // 512

    g = mf.MatchedFilter(N, ND, NT, device=DEVICE)
    g.set_data(d)
    g.set_templates(h)
    want = g.run(binsize=512, threshold=0.0)
    np.testing.assert_array_equal(got["index"], want["index"])


def test_hierarchical_upload_gating():
    """The hierarchical path caches the COARSE templates too."""
    reference = inspiral_power(N)
    H1 = np.stack([template_with_power(N, inspiral_power(N, exponent=e))
                   for e in np.linspace(-7 / 3.0, -4 / 3.0, NT)])
    H2 = np.stack([template_with_power(N, inspiral_power(N, exponent=e))
                   for e in np.linspace(-2.0, -1.5, NT)])
    d = noise((ND, N), np.random.default_rng(7))
    d[0] += (12.0 * H2[3]
             * np.exp(2j * np.pi * np.arange(N) * 411 / N)).astype(np.complex64)

    f = mf.HierarchicalFilter(N, ND, NT, snr=5.5, fd=1e-2, device=DEVICE)
    f.set_reference(reference)
    f.set_data(d)
    f.set_templates(H1)
    f.run(binsize=N, threshold=5.5)
    f.set_templates(H2)
    got = f.run(binsize=N, threshold=5.5).copy()

    g = mf.HierarchicalFilter(N, ND, NT, snr=5.5, fd=1e-2, device=DEVICE)
    g.set_reference(reference)
    g.set_data(d)
    g.set_templates(H2)
    want = g.run(binsize=N, threshold=5.5)
    np.testing.assert_array_equal(got["index"], want["index"]), \
        "the coarse templates were not rebuilt when the templates changed"


def test_a_reused_filter_is_right_across_changing_parameters():
    """Reuse ONE filter over many parameter sets, against ground truth.

    This is the shape that caught the cache bug, and the shape the suite did
    not have. The hierarchical fuzz test does reuse a filter across binsizes,
    but it compares hierarchical against flat ON THE SAME DEVICE -- and both
    were broken identically, so every bin came back -1, nothing "fired", and
    the comparison passed over an empty set.

    Comparing against a float64 reference instead of against another path of
    the same library is what makes this able to fail.
    """
    d, h = spectra(11)
    f = mf.MatchedFilter(N, ND, NT, device=DEVICE)
    f.set_data(d)
    f.set_templates(h)
    cases = [(N, None), (512, None), (256, (37, 1000)), (1000, (0, 4000)),
             (N, (100, 3000)), (64, (0, 1024)), (512, None)]
    for binsize, window in cases:
        kw = {} if window is None else {"window": window}
        got = f.run(binsize=binsize, threshold=0.0, **kw)
        lo, hi = (0, N) if window is None else window
        nb = -(-(hi - lo) // binsize)
        assert got.shape == (ND, NT, nb), (binsize, window)
        # spot-check one pair against float64
        z = np.fft.ifft(d[1].astype(np.complex128)
                        * np.conj(h[2].astype(np.complex128))) * N
        w = np.abs(z[lo:hi])
        for b in range(min(nb, 4)):
            seg = w[b * binsize:(b + 1) * binsize]
            if not seg.size:
                continue
            k = lo + b * binsize + int(np.argmax(seg))
            assert int(got["index"][1, 2, b]) == k, (binsize, window, b)


@pytest.mark.parametrize("n", [32768, 65536, 262144])
def test_above_the_gpu_range_refuses_clearly(n):
    """The GPU covers 1024 to 16384; larger must refuse, not crash or guess.

    One workgroup carries a whole transform, so 16384 is the ceiling at 1024
    threads. Larger transforms are a CPU job until the decomposition is split
    across dispatches.
    """
    with pytest.raises(ValueError, match="supports n in"):
        mf.MatchedFilter(n, 1, 2, device=DEVICE)
    with pytest.raises(ValueError, match="supports n in"):
        mf.HierarchicalFilter(n, 1, 2, snr=5.5, fd=1e-2, device=DEVICE)


@pytest.mark.parametrize("n", [32768, 262144])
def test_the_cpu_still_covers_the_larger_sizes(n):
    """Refusing on the GPU must not mean the size is unsupported."""
    rng = np.random.default_rng(0)
    d = (rng.standard_normal((1, n)) + 1j * rng.standard_normal((1, n))).astype(np.complex64)
    t = (rng.standard_normal((2, n)) + 1j * rng.standard_normal((2, n))).astype(np.complex64)
    f = mf.MatchedFilter(n, 1, 2)
    f.set_data(d)
    f.set_templates(t)
    pk = f.run(binsize=n, threshold=0.0)
    z = np.fft.ifft(d[0].astype(np.complex128) * np.conj(t[0].astype(np.complex128))) * n
    assert int(pk["index"][0, 0, 0]) == int(np.argmax(np.abs(z)))
