"""Single precision must stay single precision, at every SNR and every length.

The filter computes in complex64. That is a deliberate choice, and the thing
that would make it the wrong one is an error that grows -- with transform
length, or with signal strength, or silently after a kernel change. These
bound it.

The same sweep drives the plot on the documentation site, so a regression
shows up here as a failure and there as a visibly worse curve.
"""
import numpy as np
import pytest

from matchedfilter import precision


#: Cached because the sweep is the expensive part and every test reads it.
@pytest.fixture(scope="module")
def rows():
    return precision.sweep(ns=(1024, 4096, 16384), trials=96)


def test_magnitude_error_stays_within_a_few_float32_ulps(rows):
    """The reported magnitude against a float64 correlation at the same lag.

    Bounded at 64 eps, which is roughly 4e-6. Measured it sits near 1e-7 --
    two ULPs -- so the bound has a lot of room, on purpose: it is here to
    catch an error that has changed CHARACTER, such as a reduction done in a
    different order or a magnitude computed from a squared intermediate that
    has lost precision. A tight bound would fail on ordinary noise instead.
    """
    for r in rows:
        assert r["rel_max"] < 64 * precision.EPS32, r


def test_error_does_not_grow_with_signal_strength(rows):
    """Error must be flat in SNR, not proportional to it.

    A relative error that tracks the signal means something is being computed
    absolutely and then divided -- the error would be invisible on noise and
    grow on exactly the loud events a search cares most about getting right.
    Injected SNR spans 0 to 1000 here, so a proportional term would show as
    three orders of magnitude of growth.
    """
    for n in sorted({r["n"] for r in rows}):
        at = {r["snr"]: r["rel_median"] for r in rows if r["n"] == n}
        lo = at[min(at)]
        hi = at[max(at)]
        assert hi < 4 * max(lo, precision.EPS32 / 4), (n, at)


def test_error_grows_no_faster_than_the_transform(rows):
    """Longer transforms accumulate more rounding, but only slowly.

    A four-step transform of n points sums O(log n) terms, so the error should
    grow like log n at worst -- a 16x length increase is 1.4x more log. This
    allows 4x, which catches a step change without failing on the real growth.
    """
    ns = sorted({r["n"] for r in rows})
    worst = {n: max(r["rel_max"] for r in rows if r["n"] == n) for n in ns}
    assert worst[ns[-1]] < 4 * worst[ns[0]], worst


def test_the_reported_lag_is_the_float64_argmax(rows):
    """Where the peak is unambiguous, the filter must find the same one.

    This is not an arithmetic property and it is not promised when two lags
    are within rounding of each other -- see the all-ties case in
    tests/test_adversarial.py. But over random noise plus an injection, exact
    ties are vanishingly unlikely, so anything less than full agreement here
    means the peak scan is picking a sample that is not the maximum.
    """
    for r in rows:
        assert r["index_agreement"] == 1.0, r


def test_pure_noise_is_as_accurate_as_a_loud_signal(rows):
    """The no-signal case is not a special case.

    snr=0 is in the sweep because it is the input the filter actually sees
    almost all the time, and because an error that only appears without a
    signal would never be noticed by a test that always injects one.
    """
    for n in sorted({r["n"] for r in rows}):
        noise = next(r for r in rows if r["n"] == n and r["snr"] == 0.0)
        loud = max((r for r in rows if r["n"] == n), key=lambda r: r["snr"])
        assert noise["rel_max"] < 4 * loud["rel_max"], (noise, loud)
        assert noise["index_agreement"] == 1.0, noise


def test_sweep_reports_what_the_plot_needs():
    """The docs plot reads these fields; renaming one would empty the chart."""
    r = precision.sweep(ns=(1024,), snrs=(6.0,), trials=32)[0]
    for k in ("n", "snr", "trials", "rel_median", "rel_p90", "rel_max",
              "index_agreement"):
        assert k in r, k
    assert r["trials"] >= 32
