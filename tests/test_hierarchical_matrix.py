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
    out = ["cpu"]
    for d in mf.devices():
        if d.kind == "gpu" and not d.is_software:
            out.append(str(d))
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
    np.testing.assert_array_equal(flat_peaks["value"][fired],
                                  hier_peaks["value"][fired],
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
