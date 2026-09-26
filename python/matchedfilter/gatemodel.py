"""The coarse gate's false-dismissal rate, computed rather than tabulated.

This replaces the ACC2 accuracy table. That table stored a measured
dismissal rate per (n, taps, snr, f, B_eff, gate) cell; this derives the
same quantity from the reference profile and the algorithm, with nothing
fitted.

WHY IT CAN BE COMPUTED AT ALL. The coarse and fine stages are both maxima
over lags of a matched-filter output, and they share their in-band noise.
For a normalised in-band profile q, the output at lag tau has

    signal            rho * sqrt(f) * A(tau - L)
    E[n(t1)n*(t2)]    A(t1 - t2)          where A(d) = sum_k q_k e^(2i.pi.k.d/n)

The noise covariance IS the signal response. So one function computed from
the profile fixes the entire joint distribution of the two stages, and the
only other inputs are the coarse band and the lag spacing -- both
properties of the algorithm.

WHY THE TABLE HAD TO GO, beyond the cost of measuring it:

  * Its key was insufficient. (f, B_eff) does not determine the gate's
    behaviour: a real |H|^2/S profile and a synthetic one matched on both
    dismiss 11.7x differently at the same gate, because B_eff is only a
    second-moment proxy for the scalloping that actually matters.
  * Half of it measured nothing. `taps` has no effect since the coarse
    stage stopped interpolating, and 3500 of 3500 cell pairs were
    bit-identical across it.
  * 46-61% of its cells were zero-count -- estimating a 1e-4 probability by
    counting -- so most of the measurement bought no information.

NOISE CONVENTION. Re and Im of the filter output each have variance 1, so
|z|^2 is chi2_2 with mean 2 and SNR=5 means |z|=5. A model written with
E|n|^2 = 1 is a factor sqrt(2) too narrow and under-disperses BOTH stages,
which is indistinguishable from a missing mechanism. It is not.

Validated against the filter across fifteen configurations -- three
profile shapes, bands 512/1024/2048, snr 5.0/5.5/6.0 -- at ratios 0.88 to
1.10, and against every device, which is how an approximation in the
coarse stage (the GPU already runs it in half precision) shows up as a
calibration change rather than passing quietly. See tests/test_gate_model.py.
"""
from collections import OrderedDict

import numpy as np

#: Lag half-widths. The in-band correlation decays over ~n/B_eff samples,
#: a few coarse steps in the validated broad-band cases: nb=12/w=6 and
#: nb=4/w=3 agreed to 0.6% there. This is a local approximation, not a
#: convergence guarantee for arbitrary narrow bands; see docs/gate-model.md.
_NB = 4                      # coarse grid lags either side
_W = 3                       # fine integer lags either side

#: Per-component variance is 1, so a complex draw normalised to E|z|^2 = 1
#: is scaled by this. See the noise-convention note above.
_SIG = np.sqrt(2.0)

_CACHE = OrderedDict()
_CACHE_MAX = 64
_CACHE_BYTES = 64 * 1024 * 1024


def _samples(power, n, band, snr, nsamp, seed):
    """Joint draws of (coarse max, fine max) for one configuration."""
    pf = np.asarray(power, dtype=np.float64)
    tot = pf.sum()
    if tot <= 0:
        return None
    pf = pf / tot
    f = float(pf[:band].sum())
    f = min(max(f, 0.0), 1.0)
    if f == 0:
        return None
    step = n // band
    qb = pf[:band] / f
    out_of_band = (1.0 - f) > 1e-9

    #: A(d) = sum_k q_k exp(2i.pi.k.d/n) is an inverse DFT of the profile,
    #: so ONE transform gives it at every lag. Evaluating it as explicit
    #: complex exponentials cost O(lags x n) and dominated everything --
    #: worst at narrow bands, where a band of 64 walks 64 offsets across a
    #: lag span of 5*step. This is O(n log n), once.
    #:
    #: The out-of-band correlation needs no transform of its own:
    #: pf = f*qb + (1-f)*qo by construction, so Ao = (Af - f*Ab)/(1-f).
    def _corr(x):
        return np.fft.ifft(x) * n

    Af_t = _corr(pf)
    qb_full = np.zeros(n, dtype=np.float64)
    qb_full[:band] = qb
    Ab_t = _corr(qb_full)
    Ao_t = ((Af_t - f * Ab_t) / (1.0 - f)) if out_of_band else None
    look = lambda tab, d: tab[np.asarray(d) % n]

    gl = np.arange(-_NB, _NB + 1) * step

    rng = np.random.default_rng(seed)
    C_all, F_all = [], []
    for off in range(step):
        fl = np.arange(-_W, _W + 1) + off
        taus = np.unique(np.concatenate([fl, gl]))
        gi = np.searchsorted(taus, gl)
        lag = taus[:, None] - taus[None, :]
        eye = 1e-9 * np.eye(len(taus))
        Cb = look(Ab_t, lag); Cb = (Cb + Cb.conj().T) / 2 + eye
        Lb32 = np.linalg.cholesky(Cb).astype(np.complex64)
        m = max(nsamp // step, 256)
        w1 = (rng.standard_normal((m, len(taus)), dtype=np.float32)
              + 1j * rng.standard_normal((m, len(taus)), dtype=np.float32)
              ) / np.float32(np.sqrt(2))
        nin = (w1 @ Lb32.T) * np.float32(_SIG)
        if out_of_band:
            Co = look(Ao_t, lag); Co = (Co + Co.conj().T) / 2 + eye
            Lo32 = np.linalg.cholesky(Co).astype(np.complex64)
            w2 = (rng.standard_normal((m, len(taus)), dtype=np.float32)
                  + 1j * rng.standard_normal((m, len(taus)), dtype=np.float32)
                  ) / np.float32(np.sqrt(2))
            nout = (w2 @ Lo32.T) * np.float32(_SIG)
        else:
            nout = np.float32(0.0)
        sf = look(Af_t, taus - off).astype(np.complex64)
        sb = look(Ab_t, taus - off).astype(np.complex64)
        # Include every coarse lag in the fine maximum: they are a subset
        # of the fine grid. Even at f=1, fine-only lags can exceed the coarse
        # maximum because the coarse grid is still decimated.
        F_all.append(np.abs(np.float32(snr) * sf[None, :]
                            + np.float32(np.sqrt(f)) * nin
                            + np.float32(np.sqrt(1 - f)) * nout).max(1))
        C_all.append(np.abs(np.float32(snr * np.sqrt(f)) * sb[None, :]
                            + nin)[:, gi].max(1))
    return np.concatenate(C_all), np.concatenate(F_all)


def _conditional(power, n, band, snr, nsamp, seed=13):
    """Coarse maxima for the pairs the fine stage would have kept, sorted.

    Sorted once so any budget is a quantile lookup: the gate for fd is the
    fd-quantile of this, and a table of gates per fd is a table of indices
    into one array. That is why this costs one sample set rather than a
    root-find per budget.
    """
    p = np.asarray(power, dtype=np.float64)
    if (p.shape != (n,) or not np.isfinite(p).all() or (p < 0).any()
            or not np.isfinite(p.sum()) or p.sum() <= 0):
        raise ValueError("power must be a finite nonnegative length-n profile with positive sum")
    p = p / p.sum()
    # Use the complete bytes, not a hash alone, and include the seed and
    # exact SNR. Cache collisions or rounded SNR must not change a gate.
    key = (p.tobytes(), n, band, float(snr), nsamp, seed)
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return hit
    got = _samples(p, n, band, snr, nsamp, seed)
    if got is None:
        return None
    coarse, fine = got
    kept = np.sort(coarse[fine >= snr])
    size = len(key[0]) + kept.nbytes
    used = sum(len(k[0]) + v.nbytes for k, v in _CACHE.items())
    while _CACHE and (len(_CACHE) >= _CACHE_MAX or used + size > _CACHE_BYTES):
        oldkey, old = _CACHE.popitem(last=False)
        used -= len(oldkey[0]) + old.nbytes
    if size <= _CACHE_BYTES:
        _CACHE[key] = kept
    return kept


def _nsamp_for(fd):
    """Enough draws that the fd-quantile rests on a usable number of them.

    Scaled to the BUDGET, which the caller gives us. Roughly half the draws
    survive the detection cut, so 200/fd puts ~100 samples below the
    quantile -- about +-10%, inside the +-20% the budget is itself quoted
    to. A common fd=1e-2 costs 20k draws where a 1e-4 request needs 2M;
    flooring every gate at the tightest case made them all pay for the
    rarest one.

    Below the floor the quantile is not a measurement and gate_for returns
    None, so the caller refuses rather than guesses -- the same contract
    the table had for an unmeasured cell.
    """
    fd = max(float(fd), 1e-6)
    return int(min(max(2.0e4, 200.0 / fd), 3.0e6))


def _validate(n, band, snr, fd):
    if (not isinstance(n, (int, np.integer)) or n < 64
            or not isinstance(band, (int, np.integer)) or band < 1
            or band > n or band & (band - 1) or n % band):
        raise ValueError("n must be divisible by a power-of-two band <= n")
    if not np.isfinite(snr) or snr <= 0:
        raise ValueError("snr must be finite and positive")
    if not np.isfinite(fd) or not 0 < fd < 1:
        raise ValueError("fd must be finite and between zero and one")


def dismissal(power, n, band, snr, gate, fd_hint=1e-3):
    """Modelled false-dismissal rate at `gate`."""
    _validate(n, band, snr, fd_hint)
    if not np.isfinite(gate) or gate < 0:
        raise ValueError("gate must be finite and nonnegative")
    kept = _conditional(power, n, band, snr, _nsamp_for(fd_hint))
    if kept is None or not len(kept):
        return None
    return float(np.searchsorted(kept, float(gate)) / len(kept))


def gate_for(power, n, band, snr, fd):
    """The largest gate whose modelled dismissal still meets `fd`.

    Returns None when the budget is below what this many draws can place,
    so the caller refuses rather than guessing -- the same contract the
    table had when a cell was unmeasured.
    """
    _validate(n, band, snr, fd)
    nsamp = _nsamp_for(fd)
    if fd * nsamp < 8:
        return None
    kept = _conditional(power, n, band, snr, nsamp)
    if kept is None or not len(kept):
        return None
    idx = int(np.floor(float(fd) * len(kept)))
    if idx < 8:
        return None                      # too few draws below the budget
    return float(kept[idx])
