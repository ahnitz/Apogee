#!/usr/bin/env python3
"""Prototype of the joint (band, gate) choice, driven by the caller's reference.

The library currently picks the band from a nearest-neighbour lookup on
(n, snr, fd) that never sees the signal power, then adapts only the gate to it.
This works out what a power-driven choice would pick, so the rule can be
checked against measurement before any of it moves into C.

Cost model, in units of one full n-point pair transform:

    cost(m, U) = c_coarse(m) * (1 + p_odd*(U-1)) + rate(m) * 1

c_coarse is measured, not assumed: the even pass costs 842/1143/2030/4289 TSC
ticks a pair at m=256/512/1024/2048 against ~9800 for a full pair, which is
very close to m*log2(m)/(n*log2(n)) -- so that ratio is the model and the
measured points are the check.  rate(m) is the fraction of pairs the gate lets
through, which is what a reconstruction costs.
"""
import numpy as np


#: Measured even-pass cost, TSC ticks a pair, against ~9800 for a full pair.
#: m*log2(m) alone is a poor fit at small m -- there is a fixed cost per pass
#: that a 256-bin transform cannot amortise -- so the model carries it.
_MEASURED = {256: 842.0, 512: 1143.0, 1024: 2030.0, 2048: 4289.0}
_FULL_TICKS = 9800.0


def coarse_units(m, n):
    """Cost of one coarse pass, in units of a full n-point pair transform."""
    ms = np.array(sorted(_MEASURED), float)
    ys = np.array([_MEASURED[int(k)] / _FULL_TICKS for k in ms])
    A = np.c_[ms * np.log2(ms), np.ones_like(ms)]
    a, b = np.linalg.lstsq(A, ys, rcond=None)[0]
    return float(a * m * np.log2(m) + b)


def band_fraction(power, m):
    """Fraction of the reference's power below bin m -- the f the gate uses."""
    c = np.cumsum(np.asarray(power, float))
    return float(c[m - 1] / c[-1]) if c[-1] > 0 else 0.0


def trigger_rate(t_c, f, nlag):
    """P(coarse maximum exceeds the gate) on noise.

    Under the caller's normalisation the full statistic's squared magnitude is
    exponential with mean 2; keeping a fraction f of the band scales it to 2f.
    The maximum over nlag effectively independent lags is then the usual
    extreme-value form.  This is a ranking tool, not a calibration: it only has
    to order candidates correctly.
    """
    if f <= 0:
        return 1.0
    p1 = np.exp(-(t_c ** 2) / (2.0 * f))
    return float(1.0 - (1.0 - p1) ** nlag)


#: Cost of one reconstruction, in units of one coarse pass.  Fitted against the
#: twelve captures at gate 1.00 (bands 512/1024/2048 -> 11.92/10.09/15.97
#: ms/segment at trigger rates 8.75/1.46/0.82%), then CHECKED out of sample on
#: a bank whose power sits entirely below bin 512, where it reproduces the
#: measured order 512 < 2048 < 256.  Absolute values drift on a workload it was
#: not fitted to; the ordering, which is all selection needs, survives.
RECON_UNITS = 2.75

#: Fraction of pairs that reach the odd coarse transform.
P_ODD = 0.25


def predict_cost(power, n, m, u, t_c):
    """Relative cost of running the first stage at band m, oversample u."""
    f = band_fraction(power, m)
    rate = trigger_rate(t_c, f, m * u)
    return coarse_units(m, n) * (1.0 + P_ODD * (u - 1)) + RECON_UNITS * rate


def select(power, n, candidates, tc_of):
    """Pick the (m, u) with the lowest predicted cost.

    `tc_of(f_eff, ...)` supplies the gate for a candidate; in the library this
    is hmf_threshold, which already interpolates the measured table against the
    effective band fraction f*g^2.  That is the half of the decision that is
    already power-aware -- this adds the other half.
    """
    best, bcost = None, float('inf')
    for m, u, g in candidates:
        f = band_fraction(power, m)
        c = predict_cost(power, n, m, u, tc_of(f * g * g))
        if c < bcost:
            best, bcost = (m, u), c
    return best, bcost
