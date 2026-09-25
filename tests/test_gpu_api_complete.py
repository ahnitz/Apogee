"""Every public entry point on a GPU filter must actually use the GPU.

This file exists because of a specific class of bug that has now happened
twice, and that no correctness test can see:

  * HierarchicalFilter overrides __init__ and so never called _start_gpu.
    device= was accepted, .device reported "gpu:0", and every run went to
    the CPU and returned correct answers.
  * run_series had no GPU branch, so it built a CPU plan on demand and ran
    there -- again returning correct answers.

Both look like a working port. The only visible symptom is performance, and
performance is exactly what a correctness suite does not check. So these
tests assert on the MECHANISM: no CPU plan may come into existence on a GPU
filter, and a method that cannot run on the device must raise rather than
quietly relocate.
"""
import numpy as np
import pytest

import matchedfilter as mf

from test_api import (inspiral_power, template_with_power, noise,
                      coloured_series, overlap_save_layout)


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


@pytest.fixture
def filt():
    n, nd, nt = 4096, 3, 4
    reference = inspiral_power(n)
    H = np.stack([template_with_power(n, reference) for _ in range(nt)])
    D = noise((nd, n), np.random.default_rng(0))
    f = mf.HierarchicalFilter(n, nd, nt, snr=5.5, fd=1e-2, device=DEVICE)
    f.set_reference(reference)
    f.set_data(D)
    f.set_templates(H)
    return f, D, H, reference


def test_the_context_actually_exists(filt):
    """device= being accepted is not evidence that anything reached a GPU."""
    f = filt[0]
    assert f.device.kind == "gpu"
    assert f._gpu is not None, "device='gpu' was accepted but no context exists"


def test_run_does_not_create_a_cpu_plan(filt):
    f = filt[0]
    f.run(binsize=f.n, threshold=5.5)
    assert f._mf is None, "run() built a CPU plan on a GPU filter"


def _series_case(nt, seed=21):
    """The overlap-save layout the C expects, as test_api drives it.

    The series is SCALED so the filter output has unit-variance components,
    and one loud signal is injected. Both are required for the comparisons
    built on this fixture to check anything at all.

    Without the scaling the output peaked around 1e-5 against a gate
    calibrated at snr=5.0, so the hierarchical filter dismissed every pair on
    both devices and test_run_series_agrees_with_the_cpu compared two empty
    selections -- passing for as long as it had existed, including across a
    period when the GPU route was handing the gate spectra n times too large.
    A vacuous agreement test is worse than no test: it reports the thing it
    never looked at as working.
    """
    n, nseries, ntaps = 4096, 1 << 16, 451
    rng = np.random.default_rng(seed)
    reference = inspiral_power(n)
    H = np.stack([template_with_power(n, reference) for _ in range(nt)])
    ser = coloured_series(nseries, -7 / 3.0, rng)
    starts, ws, we = overlap_save_layout(nseries, n, ntaps)

    def block_spectrum(s):
        blk = np.zeros(n, np.complex64)
        seg = ser[int(s):int(s) + n]
        blk[:len(seg)] = seg
        return (np.fft.fft(blk) / n).astype(np.complex64)

    # Measured rather than derived: the series is coloured while |H|^2 is
    # spread over every bin, so the analytic factor is easy to get wrong.
    probe = np.fft.ifft(block_spectrum(starts[0]) * np.conj(H[0])) * n
    ser *= np.float32(1.0 / probe.real.std())       # components, not |rho|

    # One signal loud enough that the gate must keep it, in a block whose
    # window is not one of the ragged ends.
    #
    # A SCALED COPY OF THE TEMPLATE, which is what a real signal looks like.
    # The whitened form used elsewhere -- unit = H/|H|^2 -- has spectrum
    # 1/conj(H), so its power sits where the template is weakest. The matched
    # filter still reports the designed SNR, but the coarse band carries
    # almost none of it and the gate dismisses the pair on every device, for
    # the right reason. That is a signal the hierarchical filter is designed
    # NOT to find, so it cannot test whether the two devices agree.
    b = len(starts) // 2
    s0 = int(starts[b])
    t = 0
    lag = int(ws[b]) + 37
    ph = np.exp(-2j * np.pi * np.arange(n) / n).astype(np.complex64)
    inj = (H[t] * (ph ** lag) * np.float32(12.0)).astype(np.complex64)
    ser[s0:s0 + n] += (np.fft.ifft(inj) * n).astype(np.complex64)
    return n, reference, H, ser, starts, ws, we


def test_run_series_does_not_create_a_cpu_plan():
    """The method pycbc actually calls, and the one that silently fell back."""
    nt = 4
    n, reference, H, ser, starts, ws, we = _series_case(nt)
    f = mf.HierarchicalFilter(n, ndata=1, ntemplates=nt, snr=5.0, fd=1e-2,
                              device=DEVICE)
    f.set_reference(reference)
    f.set_templates(H)
    out = f.run_series(ser, starts, ws, we, binsize=n, threshold=0.0)
    assert out.shape[0] == len(starts)
    assert out.shape[1] == nt
    assert f._mf is None, "run_series built a CPU plan on a GPU filter"


def test_run_series_agrees_with_the_cpu():
    """Same blocks, both devices, compared to each other.

    The GPU does its forward transforms on the host and the CPU does them
    inside the plan, so this checks the two arrive at the same place by a
    different route.
    """
    nt = 4
    n, reference, H, ser, starts, ws, we = _series_case(nt)
    made = []
    for device in (None, DEVICE):
        g = mf.HierarchicalFilter(n, ndata=1, ntemplates=nt, snr=5.0,
                                  fd=1e-2, device=device)
        g.set_reference(reference)
        g.set_templates(H)
        # threshold at the gate's own calibration, not 0. Below snr the GPU
        # legitimately reports a SUPERSET -- it escalates the whole
        # interpolation window where the CPU interpolates -- so at threshold
        # 0 it fires 52 slots to the CPU's 4 and "the GPU invented a peak"
        # is measuring the design, not a fault. At 5.0 both give 4 and agree.
        made.append(g.run_series(ser, starts, ws, we, binsize=n,
                                 threshold=5.0).copy())
    a, b = made

    assert a.shape == b.shape
    fired = b["index"] >= 0
    # Everything below compares only where the GPU fired. If nothing fires
    # the whole test is vacuously true, which is what it was.
    assert fired.any(), (
        "nothing fired: this test compares empty selections and checks "
        "nothing. Fix the fixture, do not relax the assertions.")
    assert not (fired & (a["index"] < 0)).any(), "the GPU invented a peak"
    np.testing.assert_array_equal(a["index"][fired], b["index"][fired])
    np.testing.assert_allclose(np.abs(a["value"][fired]),
                               np.abs(b["value"][fired]), rtol=1e-4, atol=1e-4)


def test_reported_configuration_is_real(filt):
    """config() must report the taps it chose, not a placeholder.

    It returned 0 for taps at one point, which is not a configuration any
    table produces -- a reader comparing CPU and GPU would have seen it and
    had no way to tell whether the port was misconfigured or the report was.
    """
    f = filt[0]
    band, taps = f.config
    assert band in (128, 256, 512, 1024, 2048)
    assert taps > 0, "taps reported as %r" % (taps,)


def test_counters_count(filt):
    """stats() returned (0, 0) regardless of what ran."""
    f = filt[0]
    before = f.stats[0]
    f.run(binsize=f.n, threshold=5.5)
    after = f.stats[0]
    assert after > before, "stats did not advance across a run"
    assert after - before == f.ndata * f.ntemplates


def test_every_public_method_is_reachable(filt):
    """A smoke pass over the whole surface: nothing may raise NotImplemented."""
    f, D, H, _ = filt
    assert f.nbins(512) > 0
    assert 0.0 <= f.refine_rate <= 1.0
    f.set_first_stage(5.0)
    peaks, counts = f.run(binsize=f.n, threshold=5.5, counts=True)
    assert counts.shape == (f.ndata, f.ntemplates)
    idx, val = f.run(binsize=f.n, threshold=5.5, raw=True)
    assert idx.shape == val.shape
