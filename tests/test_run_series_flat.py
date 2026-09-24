"""run_series on the FLAT filter.

This existed only on HierarchicalFilter, so the wide interface -- one call
per segment instead of one per block -- could not be expressed by the flat
path at all. That is backwards: hierarchical needs a reference spectrum and
the (n, snr, fd) design tables, flat needs neither, so flat is what a caller
outside gravitational-wave search reaches for first.

The contract is equality. run_series only removes round trips, so anything it
returns that block-by-block run() does not is a bug rather than a tradeoff.
"""
import numpy as np
import pytest

import matchedfilter as mf

N = 1024
NT = 5


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


def fixture(nblk=6, stride=N // 2, seed=5):
    rng = np.random.default_rng(seed)
    ns = N + stride * nblk
    series = (rng.standard_normal(ns)
              + 1j * rng.standard_normal(ns)).astype(np.complex64)
    h = (rng.standard_normal((NT, N))
         + 1j * rng.standard_normal((NT, N))).astype(np.complex64)
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    starts = (np.arange(nblk) * stride).astype(np.uintp)
    return series, h, starts


def block_by_block(device, series, h, starts, ws, we, binsize):
    """The same blocks fed one at a time, which is what run_series replaces."""
    f = mf.MatchedFilter(N, 1, NT, device=device)
    f.set_templates(h)
    out = []
    for b in range(starts.size):
        buf = np.zeros(N, dtype=np.complex64)
        seg = series[int(starts[b]):int(starts[b]) + N]
        buf[:seg.size] = seg
        f.set_data((np.fft.fft(buf) / N).astype(np.complex64)[None, :])
        out.append(f.run(binsize=binsize, threshold=0.0,
                         window=(int(ws[b]), int(we[b])))[0].copy())
    return np.stack(out)


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("ndata", [1, 4])
@pytest.mark.parametrize("binsize", [N, N // 8])
def test_run_series_matches_block_by_block(device, ndata, binsize):
    series, h, starts = fixture()
    ws = np.zeros(starts.size, dtype=np.uintp)
    we = np.full(starts.size, N // 2, dtype=np.uintp)
    f = mf.MatchedFilter(N, ndata, NT, device=device)
    f.set_templates(h)
    got = f.run_series(series, starts, ws, we, binsize=binsize, threshold=0.0)
    ref = block_by_block(device, series, h, starts, ws, we, binsize)
    np.testing.assert_array_equal(got["index"], ref["index"])
    np.testing.assert_allclose(np.abs(got["value"]), np.abs(ref["value"]),
                               rtol=2e-4, atol=2e-5)


@pytest.mark.parametrize("device", DEVICES)
def test_grouping_is_invisible(device):
    """ndata is the grouping knob, and it cannot change any answer.

    Blocks sharing a window are filtered together, up to the plan's ndata.
    A filter built with ndata=1 groups nothing and must still agree.
    """
    series, h, starts = fixture()
    ws = np.zeros(starts.size, dtype=np.uintp)
    we = np.full(starts.size, N // 2, dtype=np.uintp)
    made = []
    for ndata in (1, 2, 3, 6):
        f = mf.MatchedFilter(N, ndata, NT, device=device)
        f.set_templates(h)
        made.append(f.run_series(series, starts, ws, we,
                                 binsize=N, threshold=0.0).copy())
    for r in made[1:]:
        np.testing.assert_array_equal(r["index"], made[0]["index"])
        np.testing.assert_allclose(np.abs(r["value"]), np.abs(made[0]["value"]),
                                   rtol=2e-4, atol=2e-5)


@pytest.mark.parametrize("device", DEVICES)
def test_a_ragged_edge_window_is_accepted(device):
    """Edge blocks have their own window; that is what run_series is for.

    It must also break the grouping -- blocks are only filtered together
    while they share a window -- without changing the answer.
    """
    series, h, starts = fixture()
    ws = np.zeros(starts.size, dtype=np.uintp)
    we = np.full(starts.size, N // 2, dtype=np.uintp)
    ws[0], we[0] = 10, N // 2 - 3
    f = mf.MatchedFilter(N, 4, NT, device=device)
    f.set_templates(h)
    got = f.run_series(series, starts, ws, we, binsize=N, threshold=0.0)
    ref = block_by_block(device, series, h, starts, ws, we, N)
    np.testing.assert_array_equal(got["index"], ref["index"])


@pytest.mark.parametrize("device", DEVICES)
def test_raw_matches_the_structured_result(device):
    series, h, starts = fixture()
    ws = np.zeros(starts.size, dtype=np.uintp)
    we = np.full(starts.size, N // 2, dtype=np.uintp)
    f = mf.MatchedFilter(N, 4, NT, device=device)
    f.set_templates(h)
    peaks = f.run_series(series, starts, ws, we, binsize=N,
                         threshold=0.0).copy()
    idx, val = f.run_series(series, starts, ws, we, binsize=N,
                            threshold=0.0, raw=True)
    np.testing.assert_array_equal(peaks["index"], idx)
    np.testing.assert_array_equal(peaks["value"], val)


@pytest.mark.parametrize("device", DEVICES)
def test_a_template_sub_range_matches_the_slice(device):
    series, h, starts = fixture()
    ws = np.zeros(starts.size, dtype=np.uintp)
    we = np.full(starts.size, N // 2, dtype=np.uintp)
    f = mf.MatchedFilter(N, 4, NT, device=device)
    f.set_templates(h)
    whole = f.run_series(series, starts, ws, we, binsize=N,
                         threshold=0.0).copy()
    part = f.run_series(series, starts, ws, we, binsize=N, threshold=0.0,
                        templates=(1, 3))
    np.testing.assert_array_equal(part["index"], whole["index"][:, 1:4])


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("klass", ["flat", "hier"])
def test_windows_with_different_bin_counts_are_refused(device, klass):
    """Regression: this corrupted the heap, on BOTH filter classes.

    peaks is addressed at a single stride taken from the first block, so a
    window yielding fewer bins wrote into the next block's row and past the
    end of the buffer. Ordinary overlap-save input reaches it -- the ragged
    edge blocks this call exists to accept are exactly the short ones -- and
    it aborted the interpreter rather than failing.

    The shape run_series returns has one nbins in it and cannot express two,
    so refusing is the answer; the crash was never a missing feature.
    """
    series, h, starts = fixture()
    ws = np.zeros(starts.size, dtype=np.uintp)
    we = np.full(starts.size, N // 2, dtype=np.uintp)
    we[0] = N // 8                      # far fewer bins than the rest
    if klass == "flat":
        f = mf.MatchedFilter(N, 4, NT, device=device)
    else:
        f = mf.HierarchicalFilter(N, 4, NT, snr=5.5, fd=1e-2, device=device)
        f.set_reference(np.abs(h[0]) ** 2)
    f.set_templates(h)
    with pytest.raises(ValueError, match="same bin count"):
        f.run_series(series, starts, ws, we, binsize=N // 8, threshold=0.0)


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("klass", ["flat", "hier"])
def test_raw_returns_two_arrays_on_every_path(device, klass):
    """One arity for raw=True, across both classes and both devices.

    HierarchicalFilter.run_series(raw=True) returned three arrays -- index,
    value and magnitude -- where every other entry point, including its OWN
    GPU branch, returned two. So the same method disagreed with itself
    depending on the device, and a caller written against the CPU raised
    "expected 3, got 2" the moment it moved to a GPU. That was the only thing
    stopping the hierarchical path running end to end under pycbc.

    The suite missed it because every test checked a backend against a
    numerical reference rather than against the other backend through the
    same call, and arity is invisible to that. This compares the paths to
    each other, which is the shape of check that catches contract drift.
    """
    series, h, starts = fixture()
    ws = np.zeros(starts.size, dtype=np.uintp)
    we = np.full(starts.size, N // 2, dtype=np.uintp)
    if klass == "flat":
        f = mf.MatchedFilter(N, 4, NT, device=device)
    else:
        f = mf.HierarchicalFilter(N, 4, NT, snr=5.5, fd=1e-2, device=device)
        f.set_reference(np.abs(h[0]) ** 2)
    f.set_templates(h)
    out = f.run_series(series, starts, ws, we, binsize=N, threshold=0.0,
                       raw=True)
    assert isinstance(out, tuple) and len(out) == 2, (
        "%s/%s run_series(raw=True) returned %d arrays, not 2"
        % (klass, device, len(out)))
    idx, val = out
    # And magnitude must be derivable, which is why it is not returned.
    peaks = f.run_series(series, starts, ws, we, binsize=N, threshold=0.0)
    np.testing.assert_array_equal(peaks["index"], idx)
    np.testing.assert_array_equal(peaks["value"], val)


@pytest.mark.parametrize("klass", ["flat", "hier"])
def test_run_raw_arity_matches_run_series(klass):
    """run and run_series must agree with each other about raw=True too."""
    series, h, starts = fixture()
    f = (mf.MatchedFilter(N, 4, NT, device="cpu") if klass == "flat"
         else mf.HierarchicalFilter(N, 4, NT, snr=5.5, fd=1e-2, device="cpu"))
    if klass == "hier":
        f.set_reference(np.abs(h[0]) ** 2)
    f.set_templates(h)
    d = np.zeros((4, N), dtype=np.complex64)
    for b in range(4):
        buf = np.zeros(N, dtype=np.complex64)
        seg = series[int(starts[b]):int(starts[b]) + N]
        buf[:seg.size] = seg
        d[b] = np.fft.fft(buf) / N
    f.set_data(d)
    a = f.run(binsize=N, threshold=0.0, raw=True)
    ws = np.zeros(starts.size, dtype=np.uintp)
    we = np.full(starts.size, N, dtype=np.uintp)
    b = f.run_series(series, starts, ws, we, binsize=N, threshold=0.0, raw=True)
    assert len(a) == len(b) == 2, (
        "%s: run gives %d arrays, run_series gives %d" % (klass, len(a), len(b)))
