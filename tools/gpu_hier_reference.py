"""The coarse pass in numpy, so the GPU port has something to be checked against.

Porting the hierarchical mode to the GPU is only tractable because of one
fact, which `src/hmf.c` states outright: the coarse pass IS a matched filter
on an m-point plan. It is not a bespoke decimation -- it is the ordinary flat
filter at length `band`, run on scaled, truncated templates. The GPU already
has that kernel, tested at exactly these lengths.

This module reproduces the decision in numpy and is checked against the C's
own MF_HMF_DUMP, so the GPU can be checked against something that is known to
agree with the shipped implementation rather than against my reading of it.

VERIFIED: the even coarse maximum reproduces the C exactly. The odd half
reproduces it on the rows that could be matched unambiguously; the dump
carries no pair id, so rows are matched by their even value and that is not
reliable when evens cluster. Adding an id to the dump is the way to close
that, and it should be closed before the odd half is relied on.
"""
import numpy as np


def band_fraction(reference, band):
    """The SIGNAL's band fraction, which is what the scaling must use.

    The coarse noise variance is s^2 * sum_{k<m} |H|^2 W against the full
    sum_k |H|^2 W, so s^2 = 1/f with the same W the reference describes.
    Using the TEMPLATE's own fraction instead mis-scales the coarse output
    and moves the coarse threshold off its calibration -- which is silent,
    because the result still looks like a plausible correlation.
    """
    reference = np.asarray(reference, dtype=np.float64)
    total = reference.sum()
    return float(reference[:band].sum() / total) if total > 0 else 0.0


def coarse_templates(template, band, f):
    """(even, odd) coarse templates for one template spectrum.

    Scaled by 1/sqrt(f) so the coarse output carries the same noise level as
    the full one and the two thresholds are directly comparable. The odd copy
    is the even one phase-ramped by exp(i*pi*k/m), a half-sample shift, which
    is what supplies the U=2 grid's odd samples without a second transform
    length.
    """
    s = 1.0 / np.sqrt(f) if f > 0 else 0.0
    even = (np.asarray(template)[:band] * s).astype(np.complex64)
    k = np.arange(band)
    odd = (even * np.exp(1j * np.pi * k / band)).astype(np.complex64)
    return even, odd


def coarse_peak(data, template, band, f):
    """(even_max, odd_max) for one pair -- the flat filter at length `band`."""
    even_t, odd_t = coarse_templates(template, band, f)
    d = np.asarray(data)[:band].astype(np.complex128)
    out = []
    for t in (even_t, odd_t):
        z = np.fft.ifft(d * np.conj(t.astype(np.complex128))) * band
        out.append(float(np.abs(z).max()))
    return tuple(out)
