"""Guardrails for replacing the measured accuracy table with a model.

The plan this protects: the coarse gate's false-dismissal rate is not
tabulated but COMPUTED, from

    dismissal = E_offset [ P( |rho*kappa(d) + u| < thr | fine detected ) ]

where kappa is the coarse stage's response to a noiseless signal at
sub-sample offset d, and u is the in-band noise the coarse and fine stages
share. The cost table is unaffected and stays measured -- it describes the
machine, which is a moving target. This describes the algorithm, which is
physics.

These tests exist so a future optimisation cannot quietly invalidate that.
They are sized to have the POWER to see a difference big enough to matter,
which is the part that is easy to get wrong: a test that compares two rare
rates at 6000 trials agrees with everything.

WHERE THE TESTS LOOK, AND WHY NOT AT THE BUDGET. Resolving a 1.5x change in
a 1e-3 rate takes ~1e5 trials. The same 1.5x at a rate near 0.1 takes ~6000,
because it is counts that buy resolution, not trials. So agreement is
checked at LOOSE gates where the rate is 1e-2 to 1e-1, and the structural
invariants (monotone in gate, in snr, in band) are what carry it down to
the budget. test_the_comparison_can_actually_see_an_invalidating_change
proves the power rather than assuming it.
"""
import pathlib
import sys

import numpy as np
import pytest

import matchedfilter as mf

sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "tools"))

PROFILE = pathlib.Path(__file__).parent / "data" / "reference_profile_pycbc.npy"
N, BAND, SNR = 4096, 1024, 5.0

#: Rates where 6000 trials give 60-600 counts, i.e. 4-13% resolution.
LOOSE_GATES = (4.4, 4.6, 4.8)

#: What "invalidating" means: the fd budget is quoted to +-20%, so a
#: systematic shift of 1.5x in the modelled rate would put a gate in the
#: wrong place by more than the budget's own stated accuracy.
INVALIDATING = 1.5


def profile():
    return np.load(PROFILE).astype(np.float64)


def loss_curve(p, band=BAND, n=N, m=64):
    """kappa(d): the coarse response over half a lag step, in closed form."""
    q = np.asarray(p[:band], dtype=np.float64)
    q = q / q.sum()
    ds = np.linspace(0.0, n / (2.0 * band), m)
    return np.abs(np.exp(2j * np.pi * np.outer(ds, np.arange(band)) / n) @ q)


_MODEL = {}


def model(p, thr, snr=SNR, band=BAND, n=N, nsamp=30000, seed=5, nb=12, w=6):
    """Predicted dismissal, from the PROFILE and the ALGORITHM only.

    Both stages are maxima over lags of a matched-filter output, and the
    two share their in-band noise. One function carries all of it: for a
    normalised in-band profile q,

        signal at lag tau     rho * sqrt(f) * A(tau - L)
        E[n(t1) conj(n(t2))]  A(t1 - t2)

    -- the noise covariance IS the signal response, so the profile alone
    fixes the whole joint distribution. The grid spacing and the two maxima
    come from the algorithm. Nothing here is fitted.

    NOISE CONVENTION, which cost a full round of wrong answers: Re and Im
    of the filter output each have variance 1, so |z|^2 is chi2_2 with mean
    2 and SNR=5 means |z|=5. Measured: Re var 0.9977, Im 0.9977, |z| mean
    1.2520 against Rayleigh sqrt(pi/2)=1.2533. A model built with
    E|n|^2 = 1 is a factor sqrt(2) too narrow and under-disperses BOTH
    stages, which looks exactly like a missing mechanism.
    """
    key = (p.tobytes().__hash__(), round(thr, 6), snr, band, n, nsamp, seed, nb, w)
    if key in _MODEL:
        return _MODEL[key]
    step = n // band
    pf = np.asarray(p, dtype=np.float64)
    pf = pf / pf.sum()
    f = pf[:band].sum()
    qb = pf[:band] / f
    kb = np.arange(band)
    Ab = lambda d: np.exp(2j * np.pi * np.asarray(d)[..., None] * kb / n) @ qb
    Af = lambda d: np.exp(2j * np.pi * np.asarray(d)[..., None] * np.arange(n) / n) @ pf
    out_of_band = (1.0 - f) > 1e-9
    if out_of_band:
        ko = np.arange(band, n)
        qo = pf[band:] / (1.0 - f)
        Ao = lambda d: np.exp(2j * np.pi * np.asarray(d)[..., None] * ko / n) @ qo

    sig = np.sqrt(2.0)                 # per-component variance 1
    r = np.random.default_rng(seed)
    gl = np.arange(-nb, nb + 1) * step
    tot = dis = 0.0
    for off in range(step):
        fl = np.arange(-w, w + 1) + off
        taus = np.unique(np.concatenate([fl, gl]))
        gi = np.searchsorted(taus, gl)
        fi = np.searchsorted(taus, fl)
        lag = taus[:, None] - taus[None, :]
        Cb = Ab(lag); Cb = (Cb + Cb.conj().T) / 2 + 1e-9 * np.eye(len(taus))
        Lb = np.linalg.cholesky(Cb)
        w1 = (r.standard_normal((nsamp, len(taus)))
              + 1j * r.standard_normal((nsamp, len(taus)))) / np.sqrt(2)
        nin = (w1 @ Lb.T) * sig
        if out_of_band:
            Co = Ao(lag); Co = (Co + Co.conj().T) / 2 + 1e-9 * np.eye(len(taus))
            w2 = (r.standard_normal((nsamp, len(taus)))
                  + 1j * r.standard_normal((nsamp, len(taus)))) / np.sqrt(2)
            nout = (w2 @ np.linalg.cholesky(Co).T) * sig
        else:
            nout = np.zeros_like(nin)
        fine = np.abs(snr * Af(taus - off)[None, :]
                      + np.sqrt(f) * nin + np.sqrt(1 - f) * nout)[:, fi].max(1)
        coarse = np.abs(snr * np.sqrt(f) * Ab(taus - off)[None, :]
                        + nin)[:, gi].max(1)
        det = fine >= snr
        tot += det.sum()
        dis += (coarse[det] < thr).sum()
    _MODEL[key] = float(dis / max(tot, 1))
    return _MODEL[key]


#: Memoised. These tests deliberately share operating points -- the
#: monotonicity check at gate 4.6 wants the same number the agreement check
#: wants -- and measure() is ~0.65s a call.
_MC = {}


def filter_mc(p, thr, trials=6000, band=BAND, n=N, snr=SNR, device=None):
    import hmf_tune as t
    key = (p.tobytes().__hash__(), round(thr, 6), trials, band, n, snr, device)
    if key not in _MC:
        dm, _, _ = t.measure(n, band, 2, 8, snr, trials, power=p, thr=thr,
                             device=device)
        _MC[key] = dm
    return _MC[key]


# --- 1. the response, deterministic ----------------------------------------

def test_kappa_matches_the_coarse_stage_it_models():
    """Measured against the real filter, by bisecting the gate on NOISELESS
    data. No Monte Carlo, so this is tight and cheap.

    This is the assumption most likely to break: reintroduce interpolation,
    change the decimation, change the lag search, and kappa moves. It is
    checked against the implementation rather than trusted.
    """
    p = profile()
    amp = np.sqrt(p)
    H = (amp / np.linalg.norm(amp)).astype(np.complex64)
    ph = np.exp(2j * np.pi * np.arange(N) / N)
    a = loss_curve(p)
    step = N // BAND
    worst = 0.0
    for off in (0.0, 1.0, 2.0):
        D = (10.0 * H * ph ** off).astype(np.complex64)[None, :]
        # One filter, 20 thresholds. Constructing it per iteration re-ran
        # device enumeration 60 times for nothing.
        hf = mf.HierarchicalFilter(N, ndata=1, ntemplates=1, snr=SNR,
                                   fd=1e-3, band=BAND, taps=8)
        hf.set_reference(p)
        hf.set_templates(H[None, :])
        hf.set_data(D)
        lo, hi = 0.0, 30.0
        for _ in range(20):
            mid = 0.5 * (lo + hi)
            hf.set_coarse_threshold(float(mid))
            kept = int(hf.run(binsize=N, threshold=0.0)["index"].ravel()[0]) >= 0
            lo, hi = (mid, hi) if kept else (lo, mid)
        want = a[min(int(round(off / (step / 2.0) * (len(a) - 1))), len(a) - 1)]
        worst = max(worst, abs(lo / 10.0 - want))
    assert worst < 0.02, (
        "the closed-form kappa is %.3f away from the coarse stage's measured "
        "response -- the model's assumption about what the coarse stage DOES "
        "no longer holds, so the formula cannot replace the table" % worst)


# --- 2. power: can the comparison see a change that matters? ---------------

def test_the_comparison_can_actually_see_an_invalidating_change():
    """A test that cannot detect the failure it guards is worse than none.

    Perturb kappa until the modelled rate moves by the invalidating factor,
    and require the comparison to reject it. This is what makes the
    agreement test below meaningful.
    """
    p = profile()
    # A 3% shift in the coarse band is a small change to the ALGORITHM, of
    # the kind an optimisation might make without noticing.
    for thr in LOOSE_GATES:
        base = model(p, thr)
        if base < 1e-3:
            continue
        bent = model(p, thr, snr=SNR * 0.97)
        assert bent / base > INVALIDATING or base / bent > INVALIDATING, (
            "a 3%% shift moved the modelled rate only %.2fx at "
            "gate %.1f -- this operating point is too insensitive to guard "
            "the model; move the gates or raise the trial count"
            % (max(bent / base, base / bent), thr))


# --- 3. structural invariants, independent of any model --------------------

@pytest.mark.parametrize("thr", LOOSE_GATES)
def test_dismissal_rises_with_the_gate(thr):
    """Monotone in the gate, by construction. Carries the loose-gate checks
    down to the budget, where counting is hopeless."""
    p = profile()
    lo = filter_mc(p, thr - 0.2)
    hi = filter_mc(p, thr)
    assert hi >= lo, (
        "gate %.1f dismisses %.3e against %.3e at the looser %.1f -- a higher "
        "gate cannot dismiss less" % (thr, hi, lo, thr - 0.2))


def test_scalloping_not_beff_is_what_predicts_dismissal():
    """The key. Two profiles matched on (f, B_eff) but differing in kappa
    must differ in dismissal, or the old key was sufficient after all."""
    import hmf_tune as t
    p = profile()
    f, be = mf._band_features(p, BAND)
    synth = t.make_ref(N, BAND, f, be)
    gp, gs = loss_curve(p).min(), loss_curve(synth).min()
    assert abs(gp - gs) > 0.02, "profiles not distinguishable in kappa"
    a = filter_mc(p, 4.6)
    b = filter_mc(synth, 4.6)
    assert max(a, b) / max(min(a, b), 1e-9) > 2.0, (
        "same (f, B_eff), kappa differs by %.3f, yet dismissal agrees "
        "(%.3e vs %.3e) -- the rekey to kappa is not justified by this data"
        % (abs(gp - gs), a, b))


# --- 4. the agreement itself ----------------------------------------------

@pytest.mark.parametrize("thr", LOOSE_GATES)
def test_model_agrees_with_the_filter(thr):
    p = profile()
    got = filter_mc(p, thr)
    want = model(p, thr)
    assert min(got, want) > 0, "no counts at gate %.1f; pick a looser one" % thr
    assert 1 / 1.3 < got / want < 1.3, (
        "model %.3e against filter %.3e at gate %.1f (%.2fx)"
        % (want, got, thr, got / want))


#: The coarse stage is where approximations go -- the GPU already runs it
#: in half precision. An approximation that changes the dismissal rate
#: changes the CALIBRATION, and the gate is placed from a rate. So the
#: model is checked against every device that has one, not just the CPU.
#:
#: Measured at the time of writing, fp16 against the CPU's float32:
#:     band 1024 gate 4.6   gpu/cpu 0.89
#:     band 1024 gate 4.8   gpu/cpu 0.97
#:     band  512 gate 4.2   gpu/cpu 0.85
#: The GPU dismisses LESS, which is the safe direction -- it escalates more
#: than its calibration asks for and loses throughput, rather than losing
#: signal. The bound here is what makes a FURTHER reduction (int8, a
#: cheaper transform, a coarser decimation) fail rather than pass quietly.
_DEVICE_TOL = 1.35


def _gpu():
    import matchedfilter as _mf
    for d in _mf.devices():
        if str(d).startswith("gpu") and not getattr(d, "software", False):
            return str(d)
    return None


@pytest.mark.parametrize("thr", LOOSE_GATES)
def test_every_device_matches_the_model(thr):
    """A device whose coarse stage drifts from the physics is a device whose
    calibration is wrong, however fast it is."""
    dev = _gpu()
    if dev is None:
        pytest.skip("no hardware GPU")
    p = profile()
    want = model(p, thr)
    got = filter_mc(p, thr, device=dev)
    assert min(got, want) > 0, "no counts at gate %.1f" % thr
    assert 1 / _DEVICE_TOL < got / want < _DEVICE_TOL, (
        "device %s dismisses %.3e against a modelled %.3e at gate %.1f "
        "(%.2fx). Its coarse stage no longer matches the physics the gate "
        "is placed from, so its calibration is wrong -- check what "
        "approximation changed." % (dev, got, want, thr, got / want))


def test_the_library_model_matches_this_one():
    """matchedfilter.gatemodel is the shipped copy of the model above.

    Two implementations of the same physics, checked against each other so
    the library's cannot drift from the one these tests validate against
    the filter.
    """
    from matchedfilter import gatemodel
    p = profile()
    for thr in LOOSE_GATES:
        a = model(p, thr)
        b = gatemodel.dismissal(p, N, BAND, SNR, thr, fd_hint=1e-2)
        assert b is not None
        assert 1 / 1.3 < a / b < 1.3, (
            "the library model gives %.3e where the reference model gives "
            "%.3e at gate %.1f" % (b, a, thr))



@pytest.mark.parametrize("fd", [.01, .001, .0001])
def test_quantile_placement_uses_the_conditional_distribution(fd):
    from matchedfilter import gatemodel as gm
    p = profile()
    gate = gm.gate_for(p, N, BAND, SNR, fd)
    kept = gm._conditional(p, N, BAND, SNR, gm._nsamp_for(fd))
    idx = int(np.floor(fd * len(kept)))
    assert gate == float(kept[idx])
    assert gm.dismissal(p, N, BAND, SNR, gate, fd_hint=fd) <= fd
    # Adjacent order statistics, not arbitrary gate tolerances.
    assert (idx + 1) / len(kept) > fd


def test_full_band_has_no_independent_noise_but_still_has_grid_loss():
    from matchedfilter import gatemodel as gm
    p = np.zeros(1024); p[:512] = 1.
    coarse, fine = gm._samples(p, 1024, 512, 5., 8000, 71)
    assert np.all(coarse <= fine + 2e-6)
    assert np.mean(coarse < .9 * fine) > .1
    # With identical lag grids, both outputs must actually coincide.
    coarse, fine = gm._samples(p, 1024, 1024, 5., 8000, 71)
    np.testing.assert_array_equal(coarse, fine)


@pytest.mark.parametrize("fd", [0., -1., 1., np.nan, np.inf])
def test_invalid_model_budget_is_rejected(fd):
    from matchedfilter import gatemodel as gm
    with pytest.raises(ValueError, match="fd"):
        gm.gate_for(np.ones(128), 128, 64, 5., fd)


@pytest.mark.parametrize("power", [np.zeros(128), np.full(128, np.nan),
                                   -np.ones(128), np.ones(127)])
def test_invalid_model_profile_is_rejected(power):
    from matchedfilter import gatemodel as gm
    with pytest.raises(ValueError, match="power"):
        gm.gate_for(power, 128, 64, 5., .01)


def test_unresolvable_budget_refuses_without_sampling(monkeypatch):
    from matchedfilter import gatemodel as gm
    def forbidden(*args, **kwargs):
        raise AssertionError("unresolvable request allocated samples")
    monkeypatch.setattr(gm, '_conditional', forbidden)
    assert gm.gate_for(np.ones(128), 128, 64, 5., 1e-8) is None


def test_sampling_cache_includes_seed_and_exact_snr(monkeypatch):
    from matchedfilter import gatemodel as gm
    from collections import OrderedDict
    monkeypatch.setattr(gm, '_CACHE', OrderedDict())
    p = np.ones(128)
    calls = []
    original = gm._samples
    def samples(*args):
        calls.append(args[3:])
        return original(*args)
    monkeypatch.setattr(gm, '_samples', samples)
    a = gm._conditional(p, 128, 64, 5., 1024, 1)
    assert gm._conditional(8*p, 128, 64, 5., 1024, 1) is a
    gm._conditional(p, 128, 64, 5., 1024, 2)
    gm._conditional(p, 128, 64, 5.00001, 1024, 1)
    assert len(calls) == 3


def test_sampling_cache_respects_memory_limit(monkeypatch):
    from matchedfilter import gatemodel as gm
    from collections import OrderedDict
    monkeypatch.setattr(gm, '_CACHE', OrderedDict())
    monkeypatch.setattr(gm, '_CACHE_BYTES', 8192)
    for seed in range(5):
        gm._conditional(np.ones(128), 128, 64, 5., 1024, seed)
    assert sum(len(k[0])+v.nbytes for k,v in gm._CACHE.items()) <= 8192
