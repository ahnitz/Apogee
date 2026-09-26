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

from test_api import (inspiral_power, template_with_power, noise,
                      coloured_series, overlap_save_layout)


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


@pytest.mark.parametrize("device", DEVICES)
def test_hierarchical_matches_flat_on_the_same_device(device):
    """Loud signals must survive the coarse pass at EVERY band.

    This is the check that caught PPG packing several pairs into one wave
    while reducing the peak with WaveActiveMax across the whole wave: the
    pairs sharing a wave received each other's maximum, only the loudest
    could match its own value in the writeback, and the rest reported -1.
    At band 128 that left 16 of 64 injections -- exactly one per group of
    four -- and the kernel looked 2.27x faster because it was discarding
    three quarters of the work.

    Nothing else here would have seen it when it was written: the
    cross-device tests need a CPU hierarchical plan, there was none for
    n=4096 band=128, and so they skipped the very band the bug lived in.
    The CPU has bands 64 and 128 now, but this stays as written -- comparing
    against the FLAT filter on the SAME device needs no plan and no table,
    so it is the one check here that does not depend on a band being
    supported, which is exactly what made it catch this.

    Bands are pinned deliberately rather than autotuned: the point is to
    exercise the small ones, where WG = band/16 falls below a wave and the
    packing that caused this is in play.
    """
    n, nt, nd = 4096, 8, 8
    rng = np.random.default_rng(5)
    power = inspiral_power(n)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    D = noise((nd, n), rng)
    for i in range(nd):                       # every pair gets a loud signal
        D[i] += (9.0 * H[i % nt]).astype(np.complex64)

    flat = mf.MatchedFilter(n, nd, nt, device=device)
    flat.set_templates(H)
    flat.set_data(D)
    fa = flat.run(binsize=n, threshold=5.0)
    assert (fa["index"] >= 0).sum() > nd * nt // 2, "the flat filter found nothing"

    for band in (128, 256, 512):
        try:
            h = mf.HierarchicalFilter(n, nd, nt, snr=5.0, fd=1e-2,
                                      band=band, taps=8, device=device)
            h.set_reference(power)
            h.set_templates(H)
            h.set_data(D)
            b = h.run(binsize=n, threshold=5.0)
        except ValueError:
            # Either no plan for this band, or no calibrated threshold for
            # it -- both refuse at run time on the GPU, because the
            # threshold is read when the reference is known. A band the
            # library declines to gate is not a band to test.
            continue
        fi, hi = fa["index"], b["index"]
        dismissed = int(((fi >= 0) & (hi < 0)).sum())
        disagree = int((((fi >= 0) & (hi >= 0)) & (fi != hi)).sum())
        assert dismissed == 0, (
            "band %d dismissed %d of %d loud signals"
            % (band, dismissed, int((fi >= 0).sum())))
        assert disagree == 0, "band %d: %d peaks differ from flat" % (band, disagree)


@pytest.mark.parametrize("device", DEVICES)
def test_manual_overrides_reach_every_backend(device):
    """Band and threshold are the ONLY manual overrides, and both must land.

    The tables are the single source of truth for the autotuned route -- the
    calibration table for the threshold, the cost table for the band. A
    caller who sets either by hand is opting out of that, and the opt-out
    has to reach whichever backend is running.

    It did not. _gpu_calibration read choose_threshold directly and never
    consulted _cal_thr, so set_coarse_threshold was silently DISCARDED on
    the GPU while working on the CPU: the plan ran at the table's value with
    no error. Nothing caught it because every other test either autotunes or
    runs on the CPU, and a wrong-but-reasonable threshold still produces
    correct peaks -- it just gates at the wrong place.
    """
    n, nt, nd = 4096, 8, 8
    power = inspiral_power(n)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    D = noise((nd, n), np.random.default_rng(1))
    for i in range(nd):                 # loud signal, or nothing clears the
        D[i] += (9.0 * H[i % nt]).astype(np.complex64)   # REPORTING threshold

    for band in (256, 512):
        h = mf.HierarchicalFilter(n, nd, nt, snr=5.5, fd=1e-2,
                                  band=band, taps=8, device=device)
        h.set_reference(power)
        h.set_templates(H)
        h.set_data(D)
        h.run(binsize=n, threshold=5.5)
        assert h.config[0] == band, (
            "%s: asked for band %d, got %s" % (device, band, h.config))

    # Check the OUTPUT, not refine_rate: that counter is CPU-only and reads
    # 0.0000 on the GPU whatever the threshold, so a test built on it passes
    # vacuously on exactly the backend the bug was on.
    #
    # A threshold of 1e9 escalates nothing, so every peak is absent. A
    # threshold of 0 escalates everything, so the result matches the flat
    # filter. If the override is dropped, both collapse to the table value
    # and the two look identical.
    outs = {}
    for thr in (0.0, 1e9):
        h = mf.HierarchicalFilter(n, nd, nt, snr=5.5, fd=1e-2,
                                  band=512, taps=8, device=device)
        h.set_reference(power)
        h.set_templates(H)
        h.set_data(D)
        h.set_coarse_threshold(thr)
        outs[thr] = h.run(binsize=n, threshold=5.5)["index"].copy()

    found_open = int((outs[0.0] >= 0).sum())
    found_shut = int((outs[1e9] >= 0).sum())
    assert found_shut == 0, (
        "%s: threshold 1e9 should dismiss everything, kept %d"
        % (device, found_shut))
    assert found_open > 0, (
        "%s: set_coarse_threshold(0) did not reach the backend -- nothing "
        "escalated, so the table value is still in force" % device)


#: Every (n, band) the library accepts selects a DIFFERENT compiled kernel:
#: the band fixes WG = band/16, which fixes PPG and TILE_T, which selects
#: among tierb_N_c16, _c16p2 and _c16p4. Testing one band at one size
#: exercises one of them. This sweep is the only thing that covers the rest.
#: 32768 and 65536 are carried by a WIDER kernel -- 32 and 64 points per
#: thread rather than 16, which changes the decomposition radix, the
#: twiddles and the digit-reversed output order together. They are in
#: this sweep for the same reason the rest are: the failure mode is a
#: peak attributed to the wrong sample, which only an index comparison
#: sees.
_MATRIX_SIZES = (1024, 2048, 4096, 8192, 16384, 32768, 65536)
_MATRIX_BANDS = (64, 128, 256, 512, 1024)


@pytest.mark.parametrize("device", DEVICES)
def test_every_size_and_band_is_correct_not_merely_runnable(device):
    """Sweep the whole (n, band) matrix and check the ANSWERS.

    Three bugs this session hid in combinations nothing exercised: a wave
    reduction that mixed pairs at band 128, a band that silently ran the
    old fp32 kernel, and a threshold extrapolated past the measured rows.
    All three produced plausible timings and correct-looking output on the
    combinations that were tested.

    So this asserts recovery and agreement, not absence of exceptions:
      * the flat filter finds the injected signal,
      * and where both report, they report the SAME peak -- which is what
        exercises the coarse and refine kernels and their index mapping at
        every compiled geometry.

    READ THE GATE CLAIM CAREFULLY. `set_coarse_threshold(0.0)` below forces
    the gate wide open on purpose, so that execution coverage does not
    depend on calibration coverage -- a size with no measured threshold
    still gets its kernels run. The consequence is that `dismissed == 0`
    CANNOT fail here: with the gate open nothing is dismissible, so that
    assertion is about the plumbing, not about the gate.

    Whether the gate dismisses correctly is a different question, and is
    tested separately -- see the threshold override test above, which runs
    the same filter at 0.0 and 1e9 and asserts the second dismisses
    everything. Do not read this sweep as evidence that a size's gate is
    calibrated: at 32768 and 65536 it is not, and a run that asks for a
    real gate raises rather than guessing.

    Combinations the library declines are skipped, not failed: not every
    band has a plan or a calibrated threshold at every size. But the count
    that DID run is asserted, so the sweep cannot quietly shrink to nothing
    -- which is exactly how the band-128 gap survived.
    """
    ran = []
    # Odd counts matter: the tile walks TILE_T consecutive templates,
    # so nt=1, 3 and 5 never divide by it and must take the untiled
    # kernel. That fallback is where the tile/dispatch mismatch hid.
    for nt in (1, 2, 3, 4, 5, 8):
      for n in _MATRIX_SIZES:
         ref = inspiral_power(n)
         H = np.stack([template_with_power(n, ref) for _ in range(nt)])
         rng = np.random.default_rng(11)
         D = noise((2, n), rng)
         for i in range(2):
             D[i] += (9.0 * H[i % nt]).astype(np.complex64)

         flat = mf.MatchedFilter(n, 2, nt, device=device)
         flat.set_templates(H)
         flat.set_data(D)
         fa = flat.run(binsize=n, threshold=5.5)
         assert (fa["index"] >= 0).any(), \
             "%s n=%d: the flat filter found nothing to compare against" % (device, n)

         for band in _MATRIX_BANDS:
             if band >= n:
                 continue
             try:
                 h = mf.HierarchicalFilter(n, 2, nt, snr=5.5, fd=1e-2,
                                           band=band, taps=8, device=device)
                 h.set_reference(ref)
                 # Exercise execution coverage independently of calibration coverage.
                 h.set_coarse_threshold(0.0)
                 h.set_templates(H)
                 h.set_data(D)
                 hb = h.run(binsize=n, threshold=5.5)
             except ValueError:
                 continue              # no plan or no calibrated gate here
             fi, hi = fa["index"], hb["index"]
             dismissed = int(((fi >= 0) & (hi < 0)).sum())
             differ = int((((fi >= 0) & (hi >= 0)) & (fi != hi)).sum())
             assert dismissed == 0, (
                 "%s n=%d band=%d dismissed %d of %d loud signals"
                 % (device, n, band, dismissed, int((fi >= 0).sum())))
             assert differ == 0, (
                 "%s n=%d band=%d: %d peaks disagree with the flat filter"
                 % (device, n, band, differ))
             ran.append((n, band))

    # Measured coverage: 24 on the CPU -- every (n, band) in the matrix with
    # band < n -- and 15 on the GPU, which is missing plans or calibrated
    # thresholds at several small bands. A floor of 10 catches a collapse on
    # a machine that legitimately supports fewer.
    assert len(ran) >= 10, (
        "%s covered only %d (n, band) combinations: %s" % (device, len(ran), ran))
    # The CPU's coverage is asserted exactly, because a gap there is the
    # thing this session closed: bands 64 and 128 had no CPU plan, so every
    # cross-device comparison skipped them, and a GPU bug at band 128 lived
    # in that gap for as long as it did because of it. If a band stops
    # running here the sweep must fail, not quietly shrink.
    if device == "cpu":
        want = {(n, b) for n in _MATRIX_SIZES for b in _MATRIX_BANDS if b < n}
        assert set(ran) == want, (
            "cpu did not run %s" % sorted(want - set(ran)))


@pytest.mark.parametrize("open_gate", [False, True])
def test_cpu_and_gpu_agree_through_run_series(open_gate):
    """Independent tuning can dismiss different peaks, never change survivors.

    Flat outputs and hierarchical outputs with an open gate must agree in
    both index and complex value. Automatically tuned gates may omit different
    peaks on different devices; each still obeys the one-sided guarantee.
    The scaled series ensures this compares hundreds of real triggers.
    """
    n, nt, ntaps, snr = 4096, 32, 451, 5.0
    rng = np.random.default_rng(7)
    ser = coloured_series(1 << 18, -7 / 3.0, rng)
    ref = inspiral_power(n)
    H = np.stack([template_with_power(n, inspiral_power(n, exponent=e))
                  for e in np.linspace(-7 / 3.0, -4 / 3.0, nt)])
    starts, ws, we = overlap_save_layout(len(ser), n, ntaps)

    # Scale so the correlation output has unit-variance components, then
    # lift it until triggers actually clear the threshold.
    blk = np.zeros(n, np.complex64)
    blk[:n] = ser[:n]
    probe = np.fft.ifft(np.fft.fft(blk) / n * np.conj(H[0])) * n
    ser = (ser * np.float32(1.7 / probe.real.std())).astype(np.complex64)

    devices = [d for d in DEVICES]
    if len(devices) < 2:
        pytest.skip("need both a CPU and a GPU to compare")

    out = {}
    for dev in devices:
        f = mf.MatchedFilter(n, 1, nt, device=dev)
        f.set_templates(H)
        out[("flat", dev)] = f.run_series(ser, starts, ws, we,
                                          binsize=n, threshold=snr)
        h = mf.HierarchicalFilter(n, 1, nt, snr=snr, fd=1e-2, device=dev,
                                  band=512 if open_gate else None)
        h.set_reference(ref)
        if open_gate:
            h.set_coarse_threshold(0)
        h.set_templates(H)
        out[("hier", dev)] = h.run_series(ser, starts, ws, we,
                                          binsize=n, threshold=snr)

    found = int((out[("flat", devices[0])]["index"] >= 0).sum())
    assert found > 500, \
        "only %d triggers: the series is not scaled and this compares " \
        "two nearly empty sets" % found

    for kind in ("flat", "hier"):
        a = out[(kind, devices[0])]["index"]
        b = out[(kind, devices[1])]["index"]
        both = (a >= 0) & (b >= 0)
        assert int((both & (a != b)).sum()) == 0, (
            "%s: %d of %d overlapping triggers at different indices"
            % (kind, int((both & (a != b)).sum()), int(both.sum())))
        if kind == "flat" or open_gate:
            np.testing.assert_array_equal(a, b)
        assert both.any()
        np.testing.assert_allclose(out[(kind, devices[0])]["value"][both],
                                   out[(kind, devices[1])]["value"][both],
                                   rtol=1e-4, atol=1e-5)

    for dev in devices:
        assert_one_sided(out[("flat", dev)], out[("hier", dev)], dev)
        if open_gate:
            np.testing.assert_array_equal(out[("flat", dev)]["index"],
                                          out[("hier", dev)]["index"])


def test_gpu_values_stay_at_roundoff_across_conditioning():
    """The GPU's SNR must match the CPU's however ill-conditioned the sum.

    A report found the GPU differing by 13% relative on triggers both
    engines place at the same time and template. The obvious explanation
    was accumulation ORDER -- float32 addition is not associative, so a
    reordered correlation sum could lose relative precision where large
    terms cancel, which is the regime whitened real data lives in.

    That explanation is WRONG, and this test is what refutes it. Sweeping
    template dynamic range over five orders of magnitude, from 8.6e+04 to
    2.0e+10, the relative difference never leaves float32 roundoff:

        dyn 8.63e+04   max rel 1.44e-06
        dyn 2.04e+03   max rel 1.14e-06
        dyn 4.94e+03   max rel 1.22e-06
        dyn 4.57e+06   max rel 6.99e-07
        dyn 2.02e+10   max rel 6.75e-07

    Conditioning does not amplify it. What IS real is the direction: the
    GPU is systematically LOWER, up to 544 of 544 points, which is a
    consistent difference in summation and not a race -- but it is bounded
    at roundoff and cannot flip a threshold.

    So this pins the bound rather than the hypothesis. If a change ever
    makes the GPU's value diverge for real, this fails with the
    conditioning it failed at, which is the first thing anyone would want
    to know.
    """
    n, nt, ntaps = 4096, 16, 451
    devices = [d for d in DEVICES]
    if len(devices) < 2:
        pytest.skip("need both a CPU and a GPU to compare")

    worst = 0.0
    checked = 0
    for expo, lowcut in ((-7 / 3.0, 0.015), (-11 / 3.0, 0.004),
                         (-23 / 3.0, 0.001)):
        k = np.arange(1, n // 2)
        p = np.zeros(n)
        p[1:n // 2] = k ** expo / ((lowcut * n / k) ** 8 + 1.0)
        p /= p.sum()
        H = np.stack([template_with_power(n, p.astype(np.float32))
                      for _ in range(nt)])
        rng = np.random.default_rng(7)
        ser = coloured_series(1 << 17, expo, rng)
        starts, ws, we = overlap_save_layout(len(ser), n, ntaps)
        blk = np.zeros(n, np.complex64)
        blk[:n] = ser[:n]
        pr = np.fft.ifft(np.fft.fft(blk) / n * np.conj(H[0])) * n
        ser = (ser * np.float32(1.7 / max(pr.real.std(), 1e-30))).astype(np.complex64)

        out = {}
        for dev in devices:
            f = mf.MatchedFilter(n, 1, nt, device=dev)
            f.set_templates(H)
            out[dev] = f.run_series(ser, starts, ws, we,
                                    binsize=n, threshold=5.0)
        a, b = out[devices[0]]["index"], out[devices[1]]["index"]
        av = np.abs(out[devices[0]]["value"])
        bv = np.abs(out[devices[1]]["value"])
        m = (a >= 0) & (b >= 0) & (a == b)
        if not m.any():
            continue
        rel = np.abs(av[m] - bv[m]) / np.maximum(av[m], 1e-30)
        worst = max(worst, float(rel.max()))
        checked += int(m.sum())
        assert float(rel.max()) < 1e-4, (
            "exponent %.2f lowcut %.3f: GPU value differs by %.2e relative "
            "at matching (block, template, index)" % (expo, lowcut, float(rel.max())))

    assert checked > 200, \
        "only %d common triggers: this compared almost nothing" % checked


def test_devices_agree_across_windows_and_binsizes():
    """Cross-device equality over the WINDOW and BINSIZE axes, values too.

    A correctness report placed a GPU argmax bug in exactly this corner:
    a restricted window with binsize equal to the WINDOW length rather than
    the transform length -- one bin over a sub-range of lags, which is the
    shape pycbc's flat path calls. The claim was that the peak search
    lands on a smaller peak in 12.6% of (block, template) pairs.

    A coverage audit explains why nothing here could have confirmed or
    refuted it: of the tests that compared two devices at all, NONE passed
    a restricted window and NONE passed binsize != n. Every cross-device
    comparison ran one bin over the full transform.

    It does not reproduce -- 270 configurations, zero mismatches -- but the
    gap was real and this closes it. Both axes matter and they interact:
    the window selects which lags are searched, the binsize partitions
    them, and an off-by-one in either shows up only when the other is not
    trivial.

    Asserts INDEX and VALUE, because an argmax bug lands on a real peak at
    a real lag: the value is self-consistent and only a cross-check against
    the other device reveals it is not the maximum.
    """
    n, nd, nt = 4096, 8, 16
    devices = [d for d in DEVICES]
    if len(devices) < 2:
        pytest.skip("need both a CPU and a GPU to compare")

    rng = np.random.default_rng(5)
    H = np.stack([template_with_power(n, inspiral_power(n, exponent=e))
                  for e in np.linspace(-7 / 3.0, -4 / 3.0, nt)])
    D = noise((nd, n), rng)
    for i in range(0, nd, 2):
        D[i] += (7.0 * H[i % nt]).astype(np.complex64)

    cases = []
    for ws, we in ((0, n), (n // 8, 7 * n // 8), (451, n), (1, n - 1),
                   (n // 4, n // 2)):
        for bs in (we - ws, n, max(1, (we - ws) // 4)):
            if 0 < bs <= n:
                cases.append((ws, we, bs))

    compared = 0
    for ws, we, bs in cases:
        out = {}
        for dev in devices:
            f = mf.MatchedFilter(n, nd, nt, device=dev)
            f.set_templates(H)
            f.set_data(D)
            out[dev] = f.run(binsize=bs, threshold=4.0, window=(ws, we))
        a, b = out[devices[0]]["index"], out[devices[1]]["index"]
        av = np.abs(out[devices[0]]["value"])
        bv = np.abs(out[devices[1]]["value"])
        both = (a >= 0) & (b >= 0)
        tag = "window=(%d,%d) binsize=%d" % (ws, we, bs)

        assert int(((a >= 0) & (b < 0)).sum()) == 0, \
            "%s: %s reports peaks %s does not" % (tag, devices[0], devices[1])
        assert int(((a < 0) & (b >= 0)).sum()) == 0, \
            "%s: %s reports peaks %s does not" % (tag, devices[1], devices[0])
        assert int((both & (a != b)).sum()) == 0, (
            "%s: %d of %d peaks at DIFFERENT lags -- an argmax divergence"
            % (tag, int((both & (a != b)).sum()), int(both.sum())))
        if both.any():
            rel = np.abs(av[both] - bv[both]) / np.maximum(av[both], 1e-30)
            assert float(rel.max()) < 1e-4, \
                "%s: values differ by %.2e relative" % (tag, float(rel.max()))
            # Every lag reported must lie inside the requested window.
            # "Scans the wrong range" and "misses a candidate inside the
            # right range" are different bugs and this separates them.
            #
            # Indices are ABSOLUTE lags in [0, n), not window-relative --
            # asserting the relative convention failed on the CPU, which
            # was this test being wrong rather than the library.
            for dev in devices:
                idx = out[dev]["index"]
                live = idx[idx >= 0]
                if live.size:
                    assert live.min() >= ws and live.max() < we, (
                        "%s: %s returned a lag outside the window, "
                        "min %d max %d" % (tag, dev, int(live.min()), int(live.max())))
        compared += int(both.sum())

    assert compared > 1000, \
        "only %d peaks compared across %d cases" % (compared, len(cases))
