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
import numpy as np

#: Lag half-widths. The in-band correlation decays over ~n/B_eff samples,
#: a few coarse steps, so the sums converge quickly: nb=12/w=6 and nb=4/w=3
#: agree to 0.6%, and nb=48 or 192 change nothing at all.
_NB = 4                      # coarse grid lags either side
_W = 3                       # fine integer lags either side

#: Per-component variance is 1, so a complex draw normalised to E|z|^2 = 1
#: is scaled by this. See the noise-convention note above.
_SIG = np.sqrt(2.0)

_CACHE = {}
_CACHE_MAX = 64


def _samples(power, n, band, snr, nsamp, seed):
    """Joint draws of (coarse max, fine max) for one configuration."""
    pf = np.asarray(power, dtype=np.float64)
    tot = pf.sum()
    if tot <= 0:
        return None
    pf = pf / tot
    f = float(pf[:band].sum())
    if f <= 0 or f >= 1.0 + 1e-12:
        f = min(max(f, 1e-12), 1.0)
    step = n // band
    kb = np.arange(band)
    qb = pf[:band] / f
    out_of_band = (1.0 - f) > 1e-9
    if out_of_band:
        ko = np.arange(band, n)
        qo = pf[band:] / (1.0 - f)

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
        #: The fine stage searches EVERY lag, so its maximum runs over all
        #: of `taus` -- not just the few around the true lag. Restricting it
        #: to those let the coarse maximum, which spans +-NB*step, exceed a
        #: fine maximum that had only looked at +-W. That is impossible
        #: whenever the coarse band is the whole band: there the coarse grid
        #: is a SUBSET of the fine's lags and the coarse can never win. It
        #: showed up as a full-band gate dismissing 7 of 78 triggers where
        #: nothing is out of band to lose.
        #:
        #: Including the coarse grid lags is what matters and costs nothing:
        #: they are already in `taus`, and a noise excursion the coarse can
        #: see is one the fine sees too.
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
    key = (np.asarray(power, dtype=np.float64).tobytes().__hash__(),
           n, band, round(float(snr), 4), nsamp)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    got = _samples(power, n, band, snr, nsamp, seed)
    if got is None:
        return None
    coarse, fine = got
    kept = np.sort(coarse[fine >= snr])
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
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


def dismissal(power, n, band, snr, gate, fd_hint=1e-3):
    """Modelled false-dismissal rate at `gate`."""
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
    kept = _conditional(power, n, band, snr, _nsamp_for(fd))
    if kept is None or not len(kept):
        return None
    idx = int(np.floor(float(fd) * len(kept)))
    if idx < 8:
        return None                      # too few draws below the budget
    return float(kept[idx])
