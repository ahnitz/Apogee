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


def model(p, thr, snr=SNR, band=BAND, n=N, nsamp=400000, seed=3, kappa=None):
    """Predicted dismissal. Two correlated Gaussians, no filtering."""
    f, _ = mf._band_features(p, band)
    a = loss_curve(p, band, n) if kappa is None else kappa
    r = np.random.default_rng(seed)
    aa = r.choice(a, nsamp)
    u = (r.standard_normal(nsamp) + 1j * r.standard_normal(nsamp)) / np.sqrt(2)
    v = (r.standard_normal(nsamp) + 1j * r.standard_normal(nsamp)) / np.sqrt(2)
    det = np.abs(snr + np.sqrt(f) * u + np.sqrt(1 - f) * v) >= snr
    if not det.any():
        return 0.0
    return float((np.abs(snr * np.sqrt(f) * aa + u)[det] < thr).mean())


#: Memoised. These tests deliberately share operating points -- the
#: monotonicity check at gate 4.6 wants the same number the agreement check
#: wants -- and measure() is ~0.65s a call. Without this the file spends
#: most of its time recomputing identical rates, which matters because this
#: is meant to be fast enough to run while iterating, not only in CI.
_MC = {}


def filter_mc(p, thr, trials=6000, band=BAND, n=N, snr=SNR):
    import hmf_tune as t
    key = (p.tobytes().__hash__(), round(thr, 6), trials, band, n, snr)
    if key not in _MC:
        dm, _, _ = t.measure(n, band, 2, 8, snr, trials, power=p, thr=thr)
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
    base_k = loss_curve(p)
    for thr in LOOSE_GATES:
        base = model(p, thr)
        if base < 1e-3:
            continue
        bent = model(p, thr, kappa=base_k * 0.97)
        assert bent / base > INVALIDATING or base / bent > INVALIDATING, (
            "a 3%% shift in kappa moved the modelled rate only %.2fx at "
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

@pytest.mark.xfail(strict=True, reason=(
    "The noise model cannot yet replace the table, and the gap is STRUCTURAL "
    "rather than a free parameter. kappa is validated to 0.6% against the "
    "real coarse stage, so the error is in the noise side. Measured against "
    "the filter at n=4096, band 1024, snr 5.0:\n"
    "    gate   filter     model\n"
    "    4.2    1.13e-03   0.00e+00\n"
    "    4.4    7.46e-03   5.79e-04\n"
    "    4.6    2.25e-02   1.85e-02\n"
    "    4.8    6.86e-02   8.71e-02\n"
    "Conditioning on 'fine detected' is too strong at tight gates and about "
    "right at loose ones. Fitting a single effective coarse-noise sigma does "
    "NOT fix it: the best value is 1.35 and it still leaves a typical 2.04x "
    "error, because no scale reproduces the shape -- at gate 4.2 even "
    "sigma=1.6 gives 3.1e-05 against a measured 1.1e-03. So the missing "
    "piece is a MECHANISM, and the first suspect is the assumption that the "
    "coarse and fine stages correlate exactly as sqrt(f): the coarse filter "
    "is a decimated band-limited thing, not the truncated template. Derive "
    "that correlation rather than assuming it; do not fit a fudge factor."))
@pytest.mark.parametrize("thr", LOOSE_GATES)
def test_model_agrees_with_the_filter(thr):
    p = profile()
    got = filter_mc(p, thr)
    want = model(p, thr)
    assert min(got, want) > 0, "no counts at gate %.1f; pick a looser one" % thr
    assert 1 / 1.2 < got / want < 1.2, (
        "model %.3e against filter %.3e at gate %.1f (%.2fx)"
        % (want, got, thr, got / want))
