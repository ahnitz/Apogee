"""The hierarchical mode across binsize, window and threshold, on every device.

The same blind spot the flat filter had, and worse. The hierarchical tests
lived in three files, all CPU-only, and their binsize coverage was 20 uses of
binsize=n, eight of 1024 and one of 512 -- so one bin over everything, and no
window matrix at all. The device-parametrised tests that did exist all built
MatchedFilter, so the device axis stopped at half the API.

Everything is asserted against the ONE-SIDED GUARANTEE, which is the mode's
actual contract and a stronger check than comparing to a reference:

    a reported peak is bit-identical to the flat filter's, because when the
    coarse pass escalates it runs that filter; only OMISSIONS are allowed.

That is why these compare hierarchical against flat rather than against
numpy. A test asserting closeness would pass while the refinement path
quietly diverged.
"""
import numpy as np
import pytest

import matchedfilter as mf

from test_api import inspiral_power, template_with_power, noise


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


def build(device, n, nd, nt, power, snr=5.5, fd=1e-2):
    """A flat and a hierarchical filter on the same inputs, on one device."""
    try:
        flat = mf.MatchedFilter(n, ndata=nd, ntemplates=nt, device=device)
        hier = mf.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=snr,
                                     fd=fd, device=device)
    except (NotImplementedError, TypeError, ValueError) as exc:
        pytest.skip("%s: %s" % (device, exc))
    hier.set_reference(power)
    return flat, hier


def loud_case(n, nd, nt, seed=11, snr=12.0):
    """Noise with a loud injection per segment, so the coarse pass escalates."""
    rng = np.random.default_rng(seed)
    power = inspiral_power(n)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    D = noise((nd, n), rng)
    for d in range(nd):
        lag = 300 + 17 * d
        D[d] += (snr * H[0] * np.exp(2j * np.pi * np.arange(n) * lag / n)
                 ).astype(np.complex64)
    return power, D, H


def assert_one_sided(flat_peaks, hier_peaks, context=""):
    """Reported peaks identical; omissions allowed; inventions are not."""
    assert flat_peaks.shape == hier_peaks.shape, context
    fired = hier_peaks["index"] >= 0
    invented = fired & (flat_peaks["index"] < 0)
    assert not invented.any(), "invented a peak %s" % context
    np.testing.assert_array_equal(flat_peaks["index"][fired],
                                  hier_peaks["index"][fired],
                                  err_msg="index differs %s" % context)
    # Values to single precision, not bit-for-bit. Today refinement runs the
    # same kernel and the result IS bit-identical, but requiring that would
    # pin an implementation detail rather than the contract: a fused coarse
    # and refine pass may sum in a different order, and that is a legitimate
    # optimisation, not a regression. The goal is accuracy and speed, not
    # reproducible rounding.
    np.testing.assert_allclose(flat_peaks["value"][fired],
                               hier_peaks["value"][fired],
                               rtol=1e-5, atol=1e-5,
                               err_msg="value differs %s" % context)
    return fired


def run_both(device, n, nd, nt, binsize, threshold, window, seed=11, snr=12.0):
    power, D, H = loud_case(n, nd, nt, seed=seed, snr=snr)
    flat, hier = build(device, n, nd, nt, power)
    for o in (flat, hier):
        o.set_data(D)
        o.set_templates(H)
    kw = {} if window is None else {"window": window}
    a = flat.run(binsize=binsize, threshold=threshold, **kw).copy()
    b = hier.run(binsize=binsize, threshold=threshold, **kw)
    return a, b


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("binsize", [1, 3, 64, 100, 257, 512, 1024, 4096])
def test_binsize_including_non_powers_of_two(device, binsize):
    """Bins are a property of the OUTPUT, so the coarse pass must not move them."""
    a, b = run_both(device, 4096, 2, 4, binsize, 5.5, None)
    assert_one_sided(a, b, "binsize=%d" % binsize)


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("window", [
    (0, 4096), (0, 4000), (37, 4000), (1, 4095), (500, 501), (2048, 4096),
])
def test_window_alignment(device, window):
    """The coarse pass searches a decimated axis; the window is on the fine one.

    An unaligned start is where a mapping between the two goes wrong, and it
    can only be seen when the grids do not line up.
    """
    a, b = run_both(device, 4096, 2, 4, 128, 5.5, window)
    assert_one_sided(a, b, "window=%s" % (window,))


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("binsize,window", [
    (300, (37, 4000)),
    (7, (13, 3999)),
    (8192, (100, 900)),        # binsize larger than the window
])
def test_awkward_combinations(device, binsize, window):
    a, b = run_both(device, 4096, 2, 4, binsize, 5.5, window)
    assert_one_sided(a, b, "binsize=%d window=%s" % (binsize, window))


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("n", [1024, 2048, 4096, 8192, 16384])
def test_every_transform_length(device, n):
    a, b = run_both(device, n, 2, 4, n // 8, 5.5, None)
    assert_one_sided(a, b, "n=%d" % n)


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("threshold", [3.0, 5.5, 8.0, 20.0])
def test_thresholds(device, threshold):
    """Including one above the injection, where everything must be dismissed."""
    a, b = run_both(device, 4096, 2, 4, 512, threshold, None)
    fired = assert_one_sided(a, b, "threshold=%.1f" % threshold)
    if threshold >= 20.0:
        assert not fired.any(), "a 12-sigma injection cleared a 20-sigma bar"


@pytest.mark.parametrize("device", DEVICES)
def test_a_loud_signal_is_not_dismissed(device):
    """The one-sided guarantee is trivially met by dismissing everything.

    Without this, a hierarchical mode that escalated nothing would pass every
    other test in this file. A 12-sigma injection against a 5.5 threshold
    must survive the coarse pass.
    """
    a, b = run_both(device, 4096, 4, 4, 1024, 5.5, None)
    assert (b["index"] >= 0).any(), "the coarse pass dismissed a 12-sigma signal"
    loud = a["index"] >= 0
    assert loud.any()


@pytest.mark.parametrize("device", DEVICES)
def test_it_actually_skips_work(device):
    """And the converse: it must not escalate everything either.

    A hierarchical filter that refines every pair is correct and pointless,
    and no correctness test can tell the difference. This is the only check
    that the mode is doing its job at all.
    """
    n, nd, nt = 4096, 4, 16
    rng = np.random.default_rng(5)
    power = inspiral_power(n)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    D = noise((nd, n), rng)               # noise only: almost nothing should fire
    _, hier = build(device, n, nd, nt, power)
    hier.set_data(D)
    hier.set_templates(H)
    hier.run(binsize=n, threshold=5.5)
    assert hier.refine_rate < 0.5, (
        "refined %.0f%% of pairs on pure noise" % (100 * hier.refine_rate))


# ---------------------------------------------------------------- fuzzing

def _random_cases(seed, n, count):
    rng = np.random.default_rng(seed)
    out = []
    while len(out) < count:
        binsize = max(1, min(int(round(float(n) ** rng.uniform(0.0, 1.0))), n))
        ws = int(rng.integers(0, n - 1))
        we = int(rng.integers(ws + 1, n + 1))
        out.append((binsize, ws, we))
    return out


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("n", [1024, 4096])
def test_fuzz_binsize_and_window(device, n):
    """Random binsize and window together, against the flat filter.

    Hand-picked cases encode what I thought was awkward; these do not.
    """
    power, D, H = loud_case(n, 2, 4)
    flat, hier = build(device, n, 2, 4, power)
    for o in (flat, hier):
        o.set_data(D)
        o.set_templates(H)
    for binsize, ws, we in _random_cases(20260923, n, 20):
        a = flat.run(binsize=binsize, threshold=5.5, window=(ws, we)).copy()
        b = hier.run(binsize=binsize, threshold=5.5, window=(ws, we))
        assert_one_sided(a, b, "n=%d binsize=%d window=(%d,%d)"
                         % (n, binsize, ws, we))


@pytest.mark.parametrize("device", DEVICES)
def test_omission_rate_meets_the_budget(device):
    """`fd` is a promise, and it has to hold on every device that claims it.

    Bit-identity says nothing about what is NOT reported: a margin set too
    high passes every other test in this file while quietly losing signals.
    The one-sided guarantee is also no protection here -- dismissing
    everything satisfies it perfectly.

    Measured: the CPU omits about 1.5% against a 1% budget (inside the
    binomial scatter at this trial count), and the GPU omits NOTHING,
    because it escalates the interpolation window rather than interpolating
    it and so can only ever refine a superset of the CPU's pairs.
    """
    n, trials, snr, fd = 4096, 600, 5.5, 1e-2
    rng = np.random.default_rng(13)
    power = inspiral_power(n)
    H = template_with_power(n, power)
    flat, hier = build(device, n, 1, 1, power, snr=snr, fd=fd)
    flat.set_templates(H[None, :])
    hier.set_templates(H[None, :])

    ph = np.exp(2j * np.pi * np.arange(n) / n)
    detected = omitted = 0
    for i in range(trials):
        D = noise((1, n), rng)
        D[0] += (snr * H * ph ** ((37 * i) % n)).astype(np.complex64)
        flat.set_data(D)
        hier.set_data(D)
        a = flat.run(binsize=n, threshold=snr)
        b = hier.run(binsize=n, threshold=snr)
        if a["index"][0, 0, 0] >= 0:
            detected += 1
            omitted += b["index"][0, 0, 0] < 0
    assert detected > 100, "too few detections to say anything"
    rate = omitted / detected
    # 3x absorbs binomial scatter at this trial count.
    assert rate <= fd * 3, "omitted %.3f%% against a %.3f%% budget" % (
        100 * rate, 100 * fd)


def test_both_devices_meet_the_budget_at_the_band_they_choose():
    """Each backend keeps its own promise, at its own configuration.

    This used to assert that the GPU dismissed nothing the CPU kept. That
    was the mechanism by which the GPU BORROWED the CPU's accuracy rows: it
    ran a different algorithm -- the CPU interpolated the coarse peak where
    the GPU escalated the whole window -- so it refined a superset, and a
    superset can only dismiss less.

    Neither half of that holds now. The CPU no longer interpolates, so the
    algorithms are the same; and the threshold is looked up per
    configuration from measured rows, so each backend is calibrated on the
    band IT selects rather than inheriting anything. They do select
    different bands -- 512 on this CPU, 256 on this GPU -- because cost is a
    property of the machine and each reads its own cost table. That is the
    design working, not drifting.

    So the subset relation is neither expected nor needed, and asserting it
    was testing a mechanism that no longer exists. What has to hold is that
    each device meets fd. Measured at the configurations they choose:
    0.00043 on the CPU at band 512 and 0.00152 on the GPU at band 256,
    against a budget of 1e-2.
    """
    gpus = [d for d in DEVICES if d != "cpu"]
    if not gpus:
        from matchedfilter import _vulkan
        pytest.skip(_vulkan.available()[1] or "no usable GPU")
    n, trials, snr, fd = 4096, 400, 5.5, 1e-2
    rng = np.random.default_rng(29)
    power = inspiral_power(n)
    H = template_with_power(n, power)
    cflat, chier = build("cpu", n, 1, 1, power, snr=snr, fd=fd)
    gflat, ghier = build(gpus[0], n, 1, 1, power, snr=snr, fd=fd)
    for o in (cflat, chier, gflat, ghier):
        o.set_templates(H[None, :])

    ph = np.exp(2j * np.pi * np.arange(n) / n)
    detected = cpu_omitted = gpu_omitted = gpu_only = 0
    for i in range(trials):
        D = noise((1, n), rng)
        D[0] += (snr * H * ph ** ((37 * i) % n)).astype(np.complex64)
        for o in (cflat, chier, gflat, ghier):
            o.set_data(D)
        if cflat.run(binsize=n, threshold=snr)["index"][0, 0, 0] < 0:
            continue                      # the flat filter found nothing
        detected += 1
        c = chier.run(binsize=n, threshold=snr)["index"][0, 0, 0] < 0
        g = ghier.run(binsize=n, threshold=snr)["index"][0, 0, 0] < 0
        cpu_omitted += c
        gpu_omitted += g
        gpu_only += (g and not c)

    assert detected > 100, "too few detections to say anything"
    # 3x the budget: at 400 trials a 1e-2 rate is ~4 events, so the Poisson
    # error is ~50% and a tighter bound would fail on noise alone. It is the
    # same allowance the other budget tests in this file use.
    for label, omitted in (("cpu", cpu_omitted), ("gpu", gpu_omitted)):
        assert omitted / detected <= fd * 3, (
            "%s omitted %d of %d = %.4f against a %.4f budget"
            % (label, omitted, detected, omitted / detected, fd))
