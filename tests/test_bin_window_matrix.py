"""Binsize and window across the awkward cases, on every available device.

The suite had a blind spot. Of 44 uses of binsize, 27 were binsize=n -- one
bin over everything -- and every window in it was aligned to the bin grid
(1024, 3072 with power-of-two bins). So the combinations that actually
stress the arithmetic were untested on the CPU as well as the GPU:

  * a binsize that is not a power of two, where the shift-instead-of-divide
    fast path must fall back to a real division
  * a binsize that does not divide the window, leaving a short final bin
  * a window START not aligned to the bin grid, so bin b covers
    [ws + b*binsize, ...) and not [b*binsize, ...)
  * windows of length 1, and binsize larger than the window

These are parametrised over device so that the GPU runs exactly the same
assertions against exactly the same reference. That matters more than it
sounds: GPU tests that call the kernel directly can never exercise binsize
or window at all, because those live in run().
"""
import numpy as np
import pytest

import matchedfilter as mf

from test_adversarial import brute


def devices():
    """cpu, plus any real GPU. Software devices are too slow for a matrix."""
    out = ["cpu"]
    for d in mf.devices():
        if d.kind == "gpu" and not d.is_software:
            out.append(str(d))
    return out


DEVICES = devices()


def spectra(n, nd, nt, seed=0):
    rng = np.random.default_rng(seed)
    d = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    t = (rng.standard_normal((nt, n)) + 1j * rng.standard_normal((nt, n))).astype(np.complex64)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    return d, t


def run_on(device, dspec, tspec, binsize, threshold, window=None):
    try:
        f = mf.MatchedFilter(dspec.shape[1], dspec.shape[0], tspec.shape[0],
                             device=device)
    except NotImplementedError as exc:
        pytest.skip(str(exc))
    f.set_data(dspec)
    f.set_templates(tspec)
    kw = {} if window is None else {"window": window}
    return f.run(binsize=binsize, threshold=threshold, **kw)


def check(device, n, binsize, window, threshold=1.0, nd=2, nt=3, seed=0):
    d, t = spectra(n, nd, nt, seed)
    ws, we = (0, n) if window is None else window
    got = run_on(device, d, t, binsize, threshold, window)
    widx, wmag = brute(d, t, binsize, threshold, ws, we)
    assert got.shape == widx.shape, "bin count disagrees with the reference"
    np.testing.assert_allclose(np.abs(got["value"]), wmag, rtol=2e-5, atol=2e-5)
    # Where the magnitude is resolved, the reported index must be the argmax.
    # Compared only where the reference actually found something: a bin with
    # nothing above threshold carries index -1 and no meaningful value.
    found = wmag > 0
    assert np.array_equal(got["index"][found], widx[found])
    assert np.all(got["index"][~found] == -1)
    return got


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("binsize", [1, 3, 64, 100, 257, 512, 1000, 1024])
def test_binsize_including_non_powers_of_two(device, binsize):
    """A binsize that is not a power of two forces the division fallback.

    The CPU shifts when it can and divides when it cannot; every binsize in
    the suite was previously shiftable, so the fallback was never run.
    """
    check(device, 1024, binsize, None)


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("window", [
    (0, 1024),        # the whole transform
    (0, 1000),        # ends mid-bin
    (37, 1000),       # starts off the grid AND ends mid-bin
    (1, 1023),        # one sample in from each end
    (500, 501),       # a single sample
    (512, 1024),      # aligned, the case the suite already had
])
def test_window_alignment(device, window):
    """An unaligned start shifts the whole bin grid.

    Bin b covers [ws + b*binsize, ...), not [b*binsize, ...). Getting that
    wrong puts every peak in a neighbouring bin, which a window aligned to
    the grid cannot reveal.
    """
    check(device, 1024, 128, window)


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("n", [1024, 2048, 4096])
@pytest.mark.parametrize("binsize,window", [
    (300, (37, 1000)),      # neither aligned nor a power of two
    (7, (13, 999)),         # tiny odd bins, odd window
    (4096, (100, 900)),     # binsize larger than the window: one short bin
])
def test_awkward_combinations(device, n, binsize, window):
    check(device, n, binsize, window)


@pytest.mark.parametrize("device", DEVICES)
def test_threshold_above_everything_empties_every_bin(device):
    """Nothing clears the threshold: every bin reports index -1, magnitude 0.

    This is the contract the CPU sets by seeding each bin's running max with
    the threshold itself, and it is what lets a GPU kernel skip almost all
    of its work -- so it has to be pinned, not assumed.
    """
    got = check(device, 1024, 128, (0, 1024), threshold=1e6)
    assert np.all(got["index"] == -1)
    assert np.all(np.abs(got["value"]) == 0.0)


@pytest.mark.parametrize("device", DEVICES)
def test_threshold_just_below_and_above_the_peak(device):
    """Straddling the threshold decides between reporting and suppressing."""
    d, t = spectra(1024, 1, 1, seed=5)
    loud = float(np.abs(np.fft.ifft(d[0].astype(np.complex128)
                                    * np.conj(t[0].astype(np.complex128))) * 1024).max())
    below = run_on(device, d, t, 1024, loud * 0.99)
    above = run_on(device, d, t, 1024, loud * 1.01)
    assert below["index"][0, 0, 0] != -1
    assert above["index"][0, 0, 0] == -1


@pytest.mark.parametrize("device", DEVICES)
def test_reported_value_matches_the_reported_index(device):
    """index, value and magnitude must describe the SAME sample.

    They are produced by different parts of the kernel and a peak-magnitude
    test cannot tell them apart -- the GPU reduction finds the magnitude
    first and recovers the index and value separately.
    """
    n, binsize = 1024, 128
    d, t = spectra(n, 2, 2, seed=9)
    got = run_on(device, d, t, binsize, 1.0)
    for i in range(2):
        for j in range(2):
            z = np.fft.ifft(d[i].astype(np.complex128)
                            * np.conj(t[j].astype(np.complex128))) * n
            for b in range(got.shape[2]):
                k = int(got["index"][i, j, b])
                if k < 0:
                    continue
                assert abs(np.abs(got["value"])[i, j, b] - abs(z[k])) < 2e-3 * abs(z[k])
                assert abs(complex(got["value"][i, j, b]) - z[k]) < 2e-3 * abs(z[k])


# ---------------------------------------------------------------- fuzzing
#
# The parametrised cases above are hand-picked, which means they encode what
# I thought was awkward. Random cases do not: they reach combinations nobody
# chose, and the bin arithmetic -- a shift or a divide, an offset grid, a
# short final bin -- is exactly the kind of code where the case that breaks
# is the one no one thought to write down.
#
# Seeded, so a failure reproduces exactly, and the case is printed in the
# assertion rather than left to be reconstructed from a parameter id.

def _random_cases(seed, n, count, with_window):
    """Varied but plausible (binsize, ws, we).

    binsize is drawn log-uniformly so small bins (many bins, heavy output)
    and large bins (one bin, the common case) both appear rather than the
    distribution piling up near n.
    """
    rng = np.random.default_rng(seed)
    cases = []
    while len(cases) < count:
        binsize = int(round(float(n) ** rng.uniform(0.0, 1.0)))
        binsize = max(1, min(binsize, n))
        if with_window:
            ws = int(rng.integers(0, n - 1))
            we = int(rng.integers(ws + 1, n + 1))
        else:
            ws, we = 0, n
        cases.append((binsize, ws, we))
    return cases


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("n", [1024, 2048])
def test_fuzz_random_binsizes(device, n):
    """Random binsizes over the whole transform."""
    for binsize, ws, we in _random_cases(seed=20260923, n=n, count=25,
                                         with_window=False):
        try:
            check(device, n, binsize, None, nd=1, nt=2)
        except AssertionError as exc:
            raise AssertionError("n=%d binsize=%d (no window): %s"
                                 % (n, binsize, exc))


@pytest.mark.parametrize("device", DEVICES)
@pytest.mark.parametrize("n", [1024, 2048])
def test_fuzz_random_binsize_and_window(device, n):
    """Random binsize AND random start/end together.

    Enabled together on purpose: an unaligned start and a binsize that does
    not divide the window interact, and either alone can look correct while
    the pair is wrong.
    """
    for binsize, ws, we in _random_cases(seed=8675309, n=n, count=25,
                                         with_window=True):
        try:
            check(device, n, binsize, (ws, we), nd=1, nt=2)
        except AssertionError as exc:
            raise AssertionError("n=%d binsize=%d window=(%d,%d): %s"
                                 % (n, binsize, ws, we, exc))


@pytest.mark.parametrize("device", DEVICES)
def test_fuzz_with_a_threshold_that_bites(device):
    """Random bins and windows, with a threshold that suppresses most bins.

    Sub-threshold bins are the path a GPU kernel skips entirely, so the
    suppressed case needs as much random coverage as the reported one.
    """
    n = 1024
    d, t = spectra(n, 1, 2, seed=3)
    z = np.fft.ifft(d[0].astype(np.complex128) * np.conj(t[0].astype(np.complex128))) * n
    thr = float(np.percentile(np.abs(z), 99.0))
    for binsize, ws, we in _random_cases(seed=4242, n=n, count=20,
                                         with_window=True):
        try:
            check(device, n, binsize, (ws, we), threshold=thr, nd=1, nt=2)
        except AssertionError as exc:
            raise AssertionError("n=%d binsize=%d window=(%d,%d) thr=%.3f: %s"
                                 % (n, binsize, ws, we, thr, exc))
