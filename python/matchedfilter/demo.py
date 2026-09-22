"""A runnable demonstration that the filter finds what it should.

Everything here is executed when the documentation page is built, and the page
shows the source of these functions next to the plots they produced. Nothing
is cached and nothing is drawn by hand: if the library stopped finding peaks,
the page would show it.

Run it yourself::

    python -m matchedfilter.demo

The cases are deliberately small -- a few hundred samples -- so a reader can
see every sample of the correlation at once.
"""

import numpy as np

import matchedfilter as mf


def make_template(n, rng):
    """A unit-norm, band-limited template spectrum.

    Band-limited because a real search's templates are, and unit-norm so that
    the filter's output reads directly as a signal-to-noise ratio.
    """
    band = n // 4
    amp = np.zeros(n)
    amp[:band] = np.exp(-np.arange(band) / (band / 3.0))
    h = (amp * np.exp(2j * np.pi * rng.random(n))).astype(np.complex64)
    return h / np.linalg.norm(h)


def make_data(n, h, rng, snr=0.0, lag=0):
    """White noise, optionally with one copy of the template buried in it.

    The filter works on spectra, so this returns a spectrum. Multiplying by
    the phase ramp is exactly a circular shift of `lag` samples in time, which
    is how the signal is placed without leaving the frequency domain.
    """
    d = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
    if snr:
        ramp = np.exp(-2j * np.pi * lag * np.arange(n) / n)
        d = d + (snr * h * ramp).astype(np.complex64)
    return d


def correlate(d, h):
    """The full correlation, by numpy, as the reference to check against.

    This is the whole answer: n samples, one per lag. The library computes the
    same thing but reports only the loudest sample per bin, which is what
    makes it fast -- so this is what it must agree with.
    """
    return np.abs(np.fft.ifft(d * np.conj(h)) * len(d))


def run_case(n, rng, snr, lag, threshold):
    """Filter one (data, template) pair and check the peak against numpy."""
    h = make_template(n, rng)
    d = make_data(n, h, rng, snr=snr, lag=lag)

    filt = mf.MatchedFilter(n, ndata=1, ntemplates=1)
    filt.set_data(d[None, :])
    filt.set_templates(h[None, :])
    peak = filt.run(binsize=n, threshold=threshold)[0, 0, 0]

    rho = correlate(d, h)
    return peak, rho


#: (label, injected SNR, lag). An SNR of 0 is pure noise: nothing was put in,
#: so nothing should come out above the threshold.
CASES = [("pure noise", 0.0, None),
         ("pure noise", 0.0, None),
         ("pure noise", 0.0, None),
         ("signal, snr 6", 6.0, 137),
         ("signal, snr 8", 8.0, 64),
         ("signal, snr 12", 12.0, 301)]


def peak_width(n, rng):
    """Half-width of the noiseless correlation peak, in samples.

    A band-limited template does not give a one-sample peak: this template
    keeps a quarter of the band, and its correlation peak is about 13 samples
    across. So at low SNR the loudest sample sits a sample or two from the
    injection, and that is the signal's shape rather than an error. Measured
    here rather than asserted, because it depends on make_template.
    """
    h = make_template(n, rng)
    rho = correlate((h * np.exp(-2j * np.pi * 0 * np.arange(n) / n)).astype(
        np.complex64), h)
    return int((rho > rho.max() / 2).sum()) // 2 + 1


def run(n=512, threshold=5.0, seed=20240917):
    """Every case, as plain data the page can plot and check."""
    rng = np.random.default_rng(seed)
    tol = peak_width(n, np.random.default_rng(seed))
    out = []
    for i, (label, snr, lag) in enumerate(CASES):
        peak, rho = run_case(n, rng, snr, lag if lag is not None else 0,
                             threshold)
        idx = int(peak["index"])
        fired = idx >= 0
        # What the page asserts: when the filter reports a peak it is the
        # loudest sample of the full correlation, and it only reports one when
        # something crossed the threshold.
        brightest = int(np.argmax(rho))
        out.append(dict(
            label=label, snr=snr, lag=lag, n=n, threshold=threshold,
            rho=[float(v) for v in rho],
            index=idx,
            magnitude=float(peak["magnitude"]) if fired else None,
            fired=bool(fired),
            brightest=brightest,
            max_rho=float(rho.max()),
            agrees=bool((not fired and rho.max() <= threshold)
                        or (fired and idx == brightest
                            and abs(float(peak["magnitude"]) - rho[brightest])
                            <= 2e-3 * max(1.0, rho[brightest]))),
            peak_tolerance=tol,
            offset=(idx - lag) if (lag is not None and fired) else None,
            found_the_signal=bool(lag is not None and fired
                                  and abs(idx - lag) <= tol),
        ))
    return out


def main():
    for c in run():
        where = "silent" if not c["fired"] else "lag %d, snr %.2f" % (
            c["index"], c["magnitude"])
        print("%-16s -> %-22s %s" % (c["label"], where,
                                     "ok" if c["agrees"] else "MISMATCH"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
