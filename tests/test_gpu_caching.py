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
    """A GPU this machine can actually run, or None -- see conftest.

    Enumeration is not availability: a driver that cannot allocate its shared
    memory still lists the adapter, and every attempt to use it then raises.
    """
    from conftest import usable_gpu
    return usable_gpu()


DEVICE = gpu_device()
def _why():
    """The actual reason, not a guess.

    "no GPU on this machine" was reported on a Mac, which has one -- the
    library simply cannot reach it. A skip that misstates the cause sends
    the reader looking in the wrong place.
    """
    from matchedfilter import _vulkan
    ok, reason = _vulkan.available()
    return reason or "no usable GPU"


pytestmark = pytest.mark.skipif(DEVICE is None, reason=_why())

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


def _vulkan_or_skip():
    """The tests below exercise the SPIR-V kernel CHOICE, which is Vulkan's.

    What these check is the selection between staging variants. That USED to
    be Vulkan's alone, and this skip used to say the Metal backend ships one
    library per size and has nothing to choose. That stopped being true when
    the portable 32 KB Metal builds were added: Metal has two variants at the
    top sizes and _stem picks between them off its own manifest field. The
    equivalent Metal coverage is test_the_chosen_metal_kernel_fits_the_device.

    What genuinely cannot move is test_both_staging_variants_agree. Comparing
    the two builds needs a device that can run BOTH, and the preferred build
    asks for 64 KB of threadgroup memory -- over the limit on every Apple GPU
    there is. So that equivalence has no Apple host, by construction rather
    than by omission.
    """
    from conftest import vulkan_runs
    ok, why = vulkan_runs()
    if not ok:
        pytest.skip(why)
    from matchedfilter import _vkcompute
    return _vkcompute


def test_the_chosen_kernel_fits_the_device():
    """Never select a kernel asking for more shared memory than exists.

    A software rasteriser hides this: llvmpipe reports 32 KB and then runs a
    64 KB kernel anyway, so the CI fallback passes where real hardware --
    Apple in particular -- would fail to create the pipeline.
    """
    V = _vulkan_or_skip()
    import json, pathlib
    man = json.loads((pathlib.Path(V.__file__).parent / "spirv"
                      / "manifest.json").read_text())
    for i, dev in enumerate(mf.devices()):
        if dev.kind != "gpu":
            continue
        ctx = V.Context(dev.index)
        try:
            for key, info in man["modules"].items():
                chosen = ctx._kernel_file(int(key))
                need = (info["lds_bytes"] if chosen == info["file"]
                        else info["portable"]["lds_bytes"])
                assert need <= ctx.max_shared_memory, (
                    "%s picked %s needing %d KB with %d KB available"
                    % (dev, chosen, need // 1024, ctx.max_shared_memory // 1024))
        finally:
            ctx.destroy()


@pytest.mark.parametrize("n", [8192, 16384])
def test_both_staging_variants_agree(n):
    """The portable build must compute the same answer, only slower."""
    V = _vulkan_or_skip()
    rng = np.random.default_rng(n)
    d = (rng.standard_normal((2, n)) + 1j * rng.standard_normal((2, n))).astype(np.complex64)
    h = (rng.standard_normal((3, n)) + 1j * rng.standard_normal((3, n))).astype(np.complex64)
    out = []
    for forced in (None, "tierb_%d_lds32.spv" % n):
        ctx = V.Context(0)
        if forced:
            ctx._kernel_file = lambda _n, f=forced: f
        try:
            out.append(ctx.peaks(n, d, h, binsize=n, threshold=0.0))
        finally:
            ctx.destroy()
    np.testing.assert_array_equal(out[0][0], out[1][0])
    np.testing.assert_allclose(np.abs(out[0][1]), np.abs(out[1][1]),
                               rtol=1e-5, atol=1e-5)


def test_the_gpu_selects_with_its_own_cost_table():
    """Cost is a property of the machine; the shipped table is a CPU's.

    Without this the GPU chose whichever band is cheapest on an AVX-512
    core -- not wrong, since any band is correct and the tables only price
    them, but measured on completely different hardware.
    """
    from test_api import inspiral_power, template_with_power
    n, nt = 1024, 4
    reference = inspiral_power(n)
    H = np.stack([template_with_power(n, reference) for _ in range(nt)])
    f = mf.HierarchicalFilter(n, 1, nt, snr=5.5, fd=1e-2, device=DEVICE)
    f.set_reference(reference)
    f.set_templates(H)
    f.set_data(np.zeros((1, n), np.complex64))
    gpu = [d for d in mf.devices() if d.kind == "gpu"][0]
    _, expected = mf.cost_table_for(gpu)
    key = f.cost_table
    if expected is None:
        # No table has been measured for this GPU yet -- only gfx11 has one.
        # Falling back to the generic table is then the RIGHT answer, and
        # asserting otherwise turns "nobody has profiled this device" into a
        # failure. What must still hold is that the filter agrees with the
        # resolver about which table that is.
        assert key is None, (
            "no table ships for %s (arch %s) yet the filter selected %r"
            % (gpu.name, gpu.arch, key))
        return
    assert key == expected, (
        "the filter used %r where the resolver picks %r for %s"
        % (key, expected, gpu.name))


def test_cost_table_resolution_order():
    """Most specific first, then family, then vendor, then generic."""
    from matchedfilter import cost_table_for
    from matchedfilter.device import Device, arch_keys

    keys = arch_keys(0x1002, "AMD Radeon 8060S Graphics (RADV GFX1151)")
    assert keys == ["gfx1151", "gfx11", "amd"]
    # nvidia and intel resolve to their vendor with no architecture tag
    assert arch_keys(0x10DE, "NVIDIA GeForce RTX 4090") == ["nvidia"]
    # a device with nothing measured falls back to the generic table
    unknown = Device("gpu", 0, "Some Other GPU", "vulkan", arch=("nope",))
    path, key = cost_table_for(unknown)
    assert key is None and path.endswith("cost.txt")


def test_the_chosen_kernel_fits_the_invocation_limit():
    """n=16384 needs a 1024-thread workgroup, exactly Apple's limit.

    A device offering fewer must refuse by name rather than fail to create
    a pipeline on the user's machine.
    """
    V = _vulkan_or_skip()
    import json, pathlib
    man = json.loads((pathlib.Path(V.__file__).parent / "spirv"
                      / "manifest.json").read_text())
    for dev in mf.devices():
        if dev.kind != "gpu":
            continue
        ctx = V.Context(dev.index)
        try:
            for key, info in man["modules"].items():
                if info["local_size"][0] <= ctx.max_invocations:
                    ctx._kernel_file(int(key))          # must not raise
                else:
                    with pytest.raises(V.VulkanError, match="thread workgroup"):
                        ctx._kernel_file(int(key))
        finally:
            ctx.destroy()


def test_accuracy_table_resolution_order():
    """Backend first, then any GPU, then the shipped default.

    ONE table ships now. accuracy-gpu.txt existed because the two backends
    ran different algorithms -- the CPU interpolated the coarse peak where
    the GPU escalated the whole window -- and it went when the CPU stopped
    interpolating. Measured after that, the GPU dismisses 0.86 to 0.97 of
    the CPU's rate, so the CPU's is an upper bound and one table serves.

    The ordering is still tested because it is what makes a future split
    possible: dropping a backend table in must change what that backend
    loads and nothing else. Tested by creating one, not by shipping one.
    """
    import os
    from matchedfilter import accuracy_table_for
    from matchedfilter.device import Device

    cpu = Device("cpu", 0, "whatever", "AVX3")
    vk = Device("gpu", 0, "some card", "vulkan")
    mtl = Device("gpu", 0, "Apple", "metal")

    # The CPU keeps the shipped default; it must never pick up a GPU table.
    path, key = accuracy_table_for(cpu)
    assert key is None and os.path.basename(path) == "accuracy.txt"

    # With no GPU table shipped, both GPU backends take the default.
    for dev in (vk, mtl):
        path, key = accuracy_table_for(dev)
        assert key is None, "%s resolved to %r" % (dev, key)
        assert os.path.basename(path) == "accuracy.txt"

    # Drop a shared GPU table in: both backends must pick it up, the CPU
    # must not. This is the split that would be needed if they diverge.
    here = os.path.dirname(path)
    shared = os.path.join(here, "accuracy-gpu.txt")
    open(shared, "w").close()
    try:
        assert accuracy_table_for(vk)[1] == "gpu"
        assert accuracy_table_for(mtl)[1] == "gpu"
        assert accuracy_table_for(cpu)[1] is None, "the CPU must never take it"
        # A backend table outranks the shared one.
        made = os.path.join(here, "accuracy-vulkan.txt")
        open(made, "w").close()
        try:
            assert accuracy_table_for(vk)[1] == "vulkan"
            assert accuracy_table_for(mtl)[1] == "gpu", "metal must not take it"
        finally:
            os.unlink(made)
    finally:
        os.unlink(shared)

    os.environ["MF_ACCURACY"] = "/tmp/whatever.txt"
    try:
        assert accuracy_table_for(vk) == ("/tmp/whatever.txt", "MF_ACCURACY")
    finally:
        del os.environ["MF_ACCURACY"]


def test_a_dropped_gpu_filter_gives_its_descriptors_back():
    """A filter that goes out of scope must release the Vulkan device.

    Nothing called Context.destroy() unless a caller did it by hand, so every
    dropped GPU filter leaked its instance and device -- a few descriptors
    each. A process that builds many then walks into RLIMIT_NOFILE, which
    Fedora ships at 1024.

    The reason this earns a test rather than a code comment is that the
    failure never mentions descriptors. It surfaced as Mesa being unable to
    create an anonymous file for its allocations, vkCreateInstance returning
    VK_ERROR_INCOMPATIBLE_DRIVER, and the GPU vanishing from enumeration
    partway through a session -- a machine that looked like it had a broken
    driver. The suite leaked 540 descriptors across 108 tests, and under a
    256 limit produced 55 failures and 34 errors naming everything except
    the cause.
    """
    import os
    import sys
    if not sys.platform.startswith("linux") or not os.path.isdir("/proc/self/fd"):
        pytest.skip("counting open descriptors needs /proc")
    if DEVICE is None:
        pytest.skip(_why())

    def nfd():
        return len(os.listdir("/proc/self/fd"))

    d, h = spectra(0)

    def once():
        f = mf.MatchedFilter(N, ND, NT, device=DEVICE)
        f.set_data(d)
        f.set_templates(h)
        f.run(binsize=N, threshold=0.0)

    once()                       # warm: one-time opens are not the leak
    import gc
    gc.collect()
    base = nfd()
    for _ in range(12):
        once()
    gc.collect()
    grown = nfd() - base
    assert grown <= 4, (
        "12 dropped GPU filters left %d descriptors behind; they used to "
        "leak about 4 each, which exhausts a 1024 limit in one session"
        % grown)
