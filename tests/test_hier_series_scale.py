"""The hierarchical GPU run_series fires where the CPU dismisses.

Found by the iteration loop (docs/iteration-plan.md) from a code reading:
the two _run_series_gpu implementations disagree about the 1/n that the C
applies on the way in. MatchedFilter's divides; HierarchicalFilter's does
not.

On PURE NOISE with a gate calibrated at snr=5.5, the correct answer is
nothing: no noise peak reaches the threshold, and the CPU reports index -1
everywhere. The GPU reports peaks, at magnitudes about n times the flat
filter's on the same data -- 0.061 to 0.087 after dividing by n=4096,
against the flat filter's 0.0742. Values that large sail past the coarse
gate, so every pair escalates and is reported.

Reproduces at every block count tried (1, 2, 3, 4, 5, 6, 8, 12).

Why the existing coverage misses it: test_run_series_agrees_with_the_cpu
compares the two devices on data containing injections, so the CPU fires
too and the comparison is made where both fired. A gate that fires when it
should stay silent is invisible to a fixture that expects firing.

FIXED. _gpu_hier received |D|max 304.633 by the run_series route against
0.0743734 by the run() route on the same blocks -- a ratio of exactly 4096.
The 1/n is now applied and this passes.

The contradiction that held the diagnosis up for a round was that
test_run_series_agrees_with_the_cpu compares magnitudes and passed
throughout. It passed because it was VACUOUS: its series was never scaled to
unit-variance output, so the filter saw peaks around 1e-5 against a gate
calibrated at snr=5.0, nothing fired on either device, and every assertion
compared two empty selections. That fixture is fixed and guarded.
"""
import numpy as np
import pytest

import matchedfilter as mf

from test_api import inspiral_power, template_with_power


def _case(nblk, n=4096, nt=8):
    p = np.asarray(inspiral_power(n), float)
    rng = np.random.default_rng(3)
    H = np.stack([template_with_power(n, p) for _ in range(nt)])
    for i in range(nt):                  # random phase leaves |H| untouched
        H[i] = (H[i] * np.exp(2j * np.pi * rng.random(n))).astype(np.complex64)
        H[i] /= np.linalg.norm(H[i])
    step = n // 2
    ns = n + step * nblk
    ser = (rng.standard_normal(ns)
           + 1j * rng.standard_normal(ns)).astype(np.complex64)
    st = (np.arange(nblk) * step).astype(np.uintp)
    ws = np.zeros(nblk, dtype=np.uintp)
    we = np.full(nblk, n // 2, dtype=np.uintp)
    return n, nt, p, H, ser, st, ws, we


@pytest.mark.parametrize("nblk", [1, 4, 6])
def test_pure_noise_is_dismissed_on_both_devices(nblk):
    from conftest import usable_gpu
    gpu = usable_gpu()
    if gpu is None:
        pytest.skip("no usable GPU")
    n, nt, p, H, ser, st, ws, we = _case(nblk)
    got = {}
    for dev in ("cpu", gpu):
        f = mf.HierarchicalFilter(n, nblk, nt, snr=5.5, fd=1e-2, device=dev)
        f.set_reference(p)
        f.set_templates(H)
        r = f.run_series(ser, st, ws, we, binsize=n, threshold=0.0)
        got[dev] = (r["index"] >= 0).sum(), float(np.abs(r["value"]).max())
    assert got["cpu"][0] == 0, "fixture is wrong: the CPU should dismiss all"
    assert got[gpu][0] == 0, (
        "the GPU reported %d peaks on pure noise (max |value| %.6g) where the "
        "CPU reported none" % (got[gpu][0], got[gpu][1]))
