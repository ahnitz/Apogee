"""Checks that do not depend on numpy's FFT being right.

Every other correctness test here compares against `np.fft.ifft`. That is the
same algorithmic family as the code under test, so a shared conceptual error
-- a normalisation, a bin ordering, a conjugation convention -- cancels on
both sides and shows nothing. FFTW's own accuracy suite compares against a
naive DFT in higher precision for exactly this reason.

So the first section here computes the correlation as a direct O(n^2) sum in
float64, from the definition, with no transform involved. The rest are
structural properties that hold regardless of how the correlation is
computed, plus the two places a batched SIMD kernel is most likely to go
wrong without anyone noticing: contamination between pairs in a batch, and
subnormal inputs, where flush-to-zero behaviour differs by instruction set.
"""
import numpy as np
import pytest

import matchedfilter as mf


# ------------------------------------------------- an independent reference

def direct_correlation(dspec, tspec):
    """The correlation from the definition: a direct sum, no FFT anywhere.

    rho[m] = sum_k  d[k] * conj(h[k]) * exp(2i*pi*k*m/n)

    which is n * IFFT(d * conj(h)) written out. O(n^2) and slow, which is why
    it is only used at short lengths -- but it shares no code, and no idea,
    with a fast transform. If this and the kernel agree, the agreement means
    something that agreeing with numpy's FFT does not.
    """
    n = dspec.shape[-1]
    k = np.arange(n)
    # exp(2i pi k m / n) built directly from the definition
    w = np.exp(2j * np.pi * np.outer(k, k) / n)
    prod = dspec.astype(np.complex128) * np.conj(tspec.astype(np.complex128))
    return np.abs(prod @ w)


@pytest.mark.parametrize("n", [256, 512])
def test_matches_a_direct_sum_not_just_another_fft(n):
    """The whole correlation, against the definition, in float64."""
    rng = np.random.default_rng(n)
    d = (rng.standard_normal((2, n)) + 1j * rng.standard_normal((2, n))).astype(np.complex64)
    h = (rng.standard_normal((2, n)) + 1j * rng.standard_normal((2, n))).astype(np.complex64)
    f = mf.MatchedFilter(n, 2, 2)
    f.set_data(d)
    f.set_templates(h)
    pk = f.run(binsize=1, threshold=0.0)          # binsize 1: every lag reported
    for i in range(2):
        for j in range(2):
            want = direct_correlation(d[i], h[j])
            got = pk["magnitude"][i, j]
            scale = float(want.max())
            assert np.allclose(got, want, rtol=0, atol=3e-6 * scale), (i, j)


def test_self_correlation_peaks_at_zero_lag_with_the_norm_squared():
    """An analytic case with no reference implementation at all.

    A template correlated with itself peaks at lag 0, and the value there is
    the sum of |h|^2 over the spectrum -- known in closed form, so this pins
    the normalisation convention rather than comparing two implementations of
    it.
    """
    n = 1024
    rng = np.random.default_rng(1)
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    f = mf.MatchedFilter(n, 1, 1)
    f.set_data(h[None, :])
    f.set_templates(h[None, :])
    pk = f.run(binsize=n, threshold=0.0)
    want = float(np.sum(np.abs(h.astype(np.complex128)) ** 2))
    assert int(pk["index"][0, 0, 0]) == 0
    assert float(pk["magnitude"][0, 0, 0]) == pytest.approx(want, rel=1e-5)


def test_flat_spectrum_correlates_to_a_single_lag():
    """Another closed form: a constant product spectrum gives a delta at lag 0.

    Every other lag is zero, so this also checks that the peak scan does not
    round a true zero into something reportable.
    """
    n = 512
    d = np.ones((1, n), np.complex64)
    h = np.ones((1, n), np.complex64)
    f = mf.MatchedFilter(n, 1, 1)
    f.set_data(d)
    f.set_templates(h)
    pk = f.run(binsize=1, threshold=0.0)
    m = pk["magnitude"][0, 0]
    assert float(m[0]) == pytest.approx(float(n), rel=1e-5)
    assert float(np.max(m[1:])) < 1e-3 * n


# ------------------------------------------------------ shift equivariance

def test_shifting_the_data_shifts_every_reported_lag():
    """Rotate the input, and every answer rotates with it.

    A structural property: it holds whatever the correlation is worth, so it
    catches indexing mistakes that a value comparison would not -- an origin
    off by one, or a wrap handled differently at the ends than in the middle.
    """
    n = 1024
    rng = np.random.default_rng(2)
    base = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    k = np.arange(n)

    def peak_of(shift):
        d = (base * np.exp(-2j * np.pi * shift * k / n)).astype(np.complex64)
        f = mf.MatchedFilter(n, 1, 1)
        f.set_data(d[None, :])
        f.set_templates(h[None, :])
        return int(f.run(binsize=n, threshold=0.0)["index"][0, 0, 0])

    at0 = peak_of(0)
    for shift in (1, 7, 100, n // 2, n - 1):
        assert peak_of(shift) == (at0 + shift) % n, shift


# --------------------------------------------------------- batch isolation

def test_a_pair_gives_the_same_answer_alone_as_in_a_batch():
    """Batching must be an optimisation, never a semantic.

    The kernel tiles over data and templates together, so a mistake in the
    tiling shows up as one pair's result depending on what else is in flight.
    That is invisible to any test that only ever runs one shape.
    """
    n, nd, nt = 1024, 6, 5
    rng = np.random.default_rng(4)
    d = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    h = (rng.standard_normal((nt, n)) + 1j * rng.standard_normal((nt, n))).astype(np.complex64)

    big = mf.MatchedFilter(n, nd, nt)
    big.set_data(d)
    big.set_templates(h)
    ref = big.run(binsize=256, threshold=0.0).copy()

    for i in range(nd):
        for j in range(nt):
            one = mf.MatchedFilter(n, 1, 1)
            one.set_data(d[i][None, :])
            one.set_templates(h[j][None, :])
            got = one.run(binsize=256, threshold=0.0)
            assert np.array_equal(got["index"][0, 0], ref["index"][i, j]), (i, j)
            assert np.array_equal(got["magnitude"][0, 0], ref["magnitude"][i, j]), (i, j)


def test_a_nan_in_one_segment_does_not_reach_the_others():
    """Containment. One bad segment must not take the batch with it.

    Real data has gaps and glitches, and a caller who hands over a batch where
    one segment is corrupt should lose that segment's answers and nothing
    else.
    """
    n, nd, nt = 512, 4, 3
    rng = np.random.default_rng(6)
    d = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    h = (rng.standard_normal((nt, n)) + 1j * rng.standard_normal((nt, n))).astype(np.complex64)

    clean = mf.MatchedFilter(n, nd, nt)
    clean.set_data(d)
    clean.set_templates(h)
    ref = clean.run(binsize=128, threshold=0.0).copy()

    bad = d.copy()
    bad[2, 17] = np.complex64(complex(np.nan, 0.0))
    f = mf.MatchedFilter(n, nd, nt)
    f.set_data(bad)
    f.set_templates(h)
    got = f.run(binsize=128, threshold=0.0)

    for i in range(nd):
        if i == 2:
            continue
        assert np.array_equal(got["index"][i], ref["index"][i]), i
        assert np.array_equal(got["magnitude"][i], ref["magnitude"][i]), i


# ----------------------------------------------------------- denormals

def test_subnormal_inputs_do_not_produce_garbage():
    """float32 subnormals, where instruction sets legitimately disagree.

    Below about 1.18e-38 float32 goes subnormal, and SIMD kernels commonly run
    with flush-to-zero set, which is a performance choice rather than a bug.
    So this does not demand the exact value. It demands that the outcome is
    one of the two defensible ones -- the correctly scaled answer, or a clean
    zero -- and never a NaN, an infinity, or a wrong lag with a plausible
    magnitude, which is the failure that would ship unnoticed.
    """
    n, lag = 1024, 321
    rng = np.random.default_rng(8)
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h /= np.linalg.norm(h)
    ramp = np.exp(-2j * np.pi * lag * np.arange(n) / n)

    for scale in (1e-30, 1e-35, 1e-38, 1e-40, 1e-44):
        d = (np.float32(scale) * h * ramp).astype(np.complex64)
        f = mf.MatchedFilter(n, 1, 1)
        f.set_data(d[None, :])
        f.set_templates(h[None, :])
        pk = f.run(binsize=n, threshold=0.0)
        m = float(pk["magnitude"][0, 0, 0])
        i = int(pk["index"][0, 0, 0])
        assert np.isfinite(m), scale
        assert m >= 0.0, scale
        if m > 0.0:
            assert i == lag, (scale, i, m)
            assert m == pytest.approx(scale, rel=1e-2), scale


def test_subnormal_behaviour_is_the_same_on_every_back_end():
    """Whatever flush-to-zero does, it must not depend on the dispatch.

    Two back ends disagreeing here would mean the same build gives different
    answers on different machines, which is worse than either answer.
    """
    n = 512
    rng = np.random.default_rng(9)
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h /= np.linalg.norm(h)
    d = (np.float32(1e-40) * h).astype(np.complex64)
    seen = {}
    for isa in mf.targets():
        mf.set_target(isa)
        f = mf.MatchedFilter(n, 1, 1)
        f.set_data(d[None, :])
        f.set_templates(h[None, :])
        pk = f.run(binsize=n, threshold=0.0)
        seen[isa] = (int(pk["index"][0, 0, 0]),
                     float(pk["magnitude"][0, 0, 0]) > 0.0)
    mf.set_target(None)          # None restores the dispatcher, not "auto"
    assert len(set(seen.values())) == 1, seen


# -------------------------------------------------------------- fuzzing

@pytest.mark.parametrize("case", range(40))
def test_random_shapes_and_windows_agree_with_the_definition(case):
    """Randomised (n, binsize, window), against a float64 reference.

    Enumerated boundary cases only cover what someone thought of. This covers
    combinations nobody did: windows that start and end at arbitrary offsets,
    bin sizes coprime with the window, and both together.
    """
    rng = np.random.default_rng(1000 + case)
    n = int(rng.choice([256, 512, 1024, 2048]))
    ws = int(rng.integers(0, n // 2))
    we = int(rng.integers(ws + 1, n + 1))
    binsize = int(rng.integers(1, max(2, (we - ws) + 1)))
    nd = int(rng.integers(1, 4))
    nt = int(rng.integers(1, 4))
    d = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    h = (rng.standard_normal((nt, n)) + 1j * rng.standard_normal((nt, n))).astype(np.complex64)

    f = mf.MatchedFilter(n, nd, nt)
    f.set_data(d)
    f.set_templates(h)
    pk = f.run(binsize=binsize, threshold=0.0, window=(ws, we))

    nb = -(-(we - ws) // binsize)
    assert pk["index"].shape == (nd, nt, nb), (n, ws, we, binsize)
    for i in range(nd):
        for j in range(nt):
            z = np.fft.ifft(d[i].astype(np.complex128)
                            * np.conj(h[j].astype(np.complex128))) * n
            w = np.abs(z[ws:we])
            scale = max(float(w.max()), 1e-30)
            for b in range(nb):
                seg = w[b * binsize:(b + 1) * binsize]
                if not seg.size:
                    continue
                k = int(np.argmax(seg))
                gi = int(pk["index"][i, j, b])
                gm = float(pk["magnitude"][i, j, b])
                assert ws + b * binsize <= gi < ws + b * binsize + seg.size
                # the reported lag must attain the bin maximum, which is
                # what is promised -- ties make the index itself unspecified
                assert w[gi - ws] == pytest.approx(seg[k], rel=1e-5), (case, b)
                assert gm == pytest.approx(seg[k], rel=2e-5, abs=1e-6 * scale)
