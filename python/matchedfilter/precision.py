"""How closely the single-precision filter tracks a float64 reference.

The filter computes in complex64 and reports one peak per bin. A float64
numpy correlation of the same inputs is the truth it has to agree with. This
sweeps injected SNR and measures the disagreement, because the answer is not
a single number: at high SNR the peak is far above the noise and the error is
the transform's own rounding, while near the threshold the peak competes with
noise samples a hair below it and *which* sample wins can legitimately differ.

Those two effects are reported separately, and keeping them apart is the
point:

  * **magnitude error** -- the reported magnitude against the float64
    correlation evaluated AT THE LAG THE FILTER REPORTED. This is pure
    arithmetic, and it should sit near the float32 epsilon at every SNR.

  * **index agreement** -- how often the reported lag is the float64 argmax.
    This is not an arithmetic property. When two lags are within rounding of
    each other, either is a correct answer to "where is the maximum", and
    disagreement here says the peak was ambiguous, not that the filter is
    wrong.

Run it yourself::

    python -m matchedfilter.precision
"""

import numpy as np

import matchedfilter as mf

#: Injected SNRs. Spans from below a typical search threshold, where the peak
#: is not clearly separated from noise, to far above it, where it is.
SNRS = (0.0, 4.0, 5.0, 6.0, 8.0, 12.0, 20.0, 50.0, 200.0, 1000.0)


def reference(dspec, tspec):
    """The whole correlation in float64 -- the answer to be checked against."""
    n = dspec.shape[-1]
    return np.abs(np.fft.ifft(dspec.astype(np.complex128)
                              * np.conj(tspec.astype(np.complex128))) * n)


def one_batch(n, snr, batch, rng):
    """One batch of pure-noise data with a copy of the template injected.

    Injection is a phase ramp on the spectrum, which is exactly a circular
    shift, so the signal lands at a known lag with no resampling error of its
    own to confuse the measurement.
    """
    h = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    h /= np.linalg.norm(h)
    d = (rng.standard_normal((batch, n))
         + 1j * rng.standard_normal((batch, n))).astype(np.complex64)
    lags = rng.integers(0, n, size=batch)
    if snr:
        k = np.arange(n)
        for j, lag in enumerate(lags):
            d[j] += (snr * h * np.exp(-2j * np.pi * lag * k / n)).astype(np.complex64)

    filt = mf.MatchedFilter(n, ndata=batch, ntemplates=1)
    filt.set_data(d)
    filt.set_templates(h[None, :])
    peaks = filt.run(binsize=n, threshold=0.0)

    rel, hit = [], 0
    for j in range(batch):
        ref = reference(d[j], h)
        i = int(peaks["index"][j, 0, 0])
        m = float(np.abs(peaks["value"])[j, 0, 0])
        scale = float(ref.max())
        if scale <= 0:
            continue
        # Error at the lag the filter chose: arithmetic only, no tie effects.
        rel.append(abs(m - float(ref[i])) / scale)
        hit += int(i == int(np.argmax(ref)))
    return rel, hit, batch


#: Transform lengths swept. Error should grow slowly with n -- a longer
#: transform accumulates more rounding -- and showing that is most of the
#: reason to plot this rather than quote one number.
NS = (1024, 4096, 16384, 65536)


def sweep(ns=NS, snrs=SNRS, trials=192, batch=32, seed=20240921):
    """Magnitude error and index agreement at each (length, injected SNR)."""
    out = []
    for n in ns:
        out += _sweep_one(n, snrs, trials, batch, seed)
    return out


def _sweep_one(n, snrs, trials, batch, seed):
    rng = np.random.default_rng(seed + n)
    out = []
    for snr in snrs:
        rel, hit, tot = [], 0, 0
        while tot < trials:
            b = min(batch, trials - tot)
            r, hi, nb = one_batch(n, float(snr), b, rng)
            rel += r
            hit += hi
            tot += nb
        a = np.array(rel) if rel else np.zeros(1)
        # A histogram of the errors, not only their summary. The median and
        # the worst case say where the distribution sits and how far it
        # reaches; they do not say whether it is a tight pile near the float32
        # epsilon or something with a tail, and those are different claims
        # about the arithmetic. Logarithmic bins, since the values span
        # decades.
        lo, hi = 1e-9, 1e-5
        edges = np.logspace(np.log10(lo), np.log10(hi), 25)
        hist = np.histogram(np.clip(a, lo, hi * 0.999), bins=edges)[0]
        out.append(dict(
            n=n, snr=float(snr), trials=int(tot),
            hist=[int(x) for x in hist],
            hist_edges=[float(x) for x in edges],
            rel_median=float(np.median(a)),
            rel_p90=float(np.percentile(a, 90)),
            rel_max=float(a.max()),
            index_agreement=float(hit) / max(tot, 1),
        ))
    return out


#: float32 has 24 bits of significand, so the smallest representable relative
#: step is 2^-24. A correlation of n points accumulates rounding across the
#: transform, so the floor is that epsilon times a growth term, not the
#: epsilon itself.
EPS32 = 2.0 ** -24


def main():
    print("magnitude error against a float64 correlation, and how often the "
          "reported lag\nis the float64 argmax. float32 eps = %.2e\n" % EPS32)
    print("  %8s %8s %12s %12s %12s %12s"
          % ("n", "snr", "median", "p90", "max", "index agree"))
    for r in sweep():
        print("  %8d %8.1f %12.2e %12.2e %12.2e %11.1f%%"
              % (r["n"], r["snr"], r["rel_median"], r["rel_p90"], r["rel_max"],
                 100 * r["index_agreement"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
