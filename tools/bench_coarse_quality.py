#!/usr/bin/env python3
"""Is the even/odd split worth it, or is a wider single band better?

The coarse statistic is worth exactly what it recovers of the true SNR,
because the trigger rate falls as exp(-t^2/2) and the threshold is set by the
WORST case, not the average. Two things cost recovery:

  f          the fraction of the template's power inside the band. A wider
             band captures more of it.  Bounded above by sqrt(f).
  scalloping the peak falls between coarse lag samples. A critically sampled
             band loses up to 18%; oversampling by 2 (the even/odd split)
             removes almost all of it.

So the question is whether spending the second transform on OVERSAMPLING a
narrow band beats spending it on WIDENING a critically sampled one. That is
an empirical trade and this measures it, sweeping the sub-sample offset
because the minimum over offset is what sets the threshold.

Run:  python tools/bench_coarse_quality.py
"""
import sys

import numpy as np

sys.path.insert(0, "tests")
from test_api import inspiral_power, template_with_power


def recovery(n, band, U, power, offsets, rng):
    """min and mean of coarse/full over sub-sample offsets, and f."""
    H = template_with_power(n, power).astype(np.complex64)
    f = float(power[:band].sum() / power.sum())
    tw = np.exp(1j * np.pi * np.arange(band) / band)      # half-sample shift
    mins, means = [], []
    for off in offsets:
        # A signal at a FRACTIONAL lag: a pure phase ramp is an exact
        # sub-sample shift, so no interpolation error is introduced here.
        ramp = np.exp(-2j * np.pi * np.arange(n) * off / n).astype(np.complex64)
        Dsig = (H * ramp).astype(np.complex64)
        full = np.abs(np.fft.ifft(Dsig * np.conj(H)) * n).max()
        prod = Dsig[:band] * np.conj(H[:band])
        even = np.abs(np.fft.ifft(prod) * band).max()
        if U == 1:
            c = even
        else:
            odd = np.abs(np.fft.ifft(prod * tw) * band).max()
            c = max(even, odd)
        mins.append(c / full)
        means.append(c / full)
    return float(np.min(mins)), float(np.mean(means)), f


def main():
    n = 4096
    power = np.asarray(inspiral_power(n), float)
    rng = np.random.default_rng(0)
    # Offsets across one coarse grid step. The step is n/band lags, so a
    # sweep in whole input samples covers it for every band here.
    print("device-independent: this is arithmetic, not a benchmark")
    print("n = %d\n" % n)
    print("%-6s %-3s %-9s %-9s %-9s %-11s %s"
          % ("band", "U", "f", "sqrt(f)", "worst", "mean", "transform cost"))
    rows = []
    for band in (128, 256, 512, 1024, 2048):
        step = n / band
        offsets = np.linspace(0.0, step, 17)
        for U in (1, 2):
            w, m, f = recovery(n, band, U, power, offsets, rng)
            # cost in units of band*log2(band); U=2 pays a second transform,
            # but only for the pairs that survive the even gate.
            unit = band * np.log2(band)
            cost_ungated = unit * U
            rows.append((band, U, f, w, m, cost_ungated))
            print("%-6d %-3d %-9.4f %-9.4f %-9.4f %-11.4f %.0f"
                  % (band, U, f, np.sqrt(f), w, m, cost_ungated))

    # The odd half is GATED: it runs only for pairs surviving the even
    # threshold, measured at 12-25% on this fixture. Costing U=2 at two full
    # transforms overstates it by a factor of nearly two, which inverts the
    # conclusion -- so the survival fraction is the parameter that decides
    # this, and it is swept rather than assumed.
    print("\nWorst-case recovery per unit of transform cost.")
    print("U=2 pays its second transform only for pairs surviving the even")
    print("gate, so its cost depends on that survival fraction s.\n")
    for s_gate in (0.10, 0.25, 0.50, 1.00):
        print("  even-gate survival s = %.0f%%" % (100 * s_gate))
        print("    %-14s %-10s %-10s %s" % ("option", "cost", "worst", ""))
        opts = []
        for band, U, f, w, m, c_ungated in rows:
            unit = band * np.log2(band)
            cost = unit * (1.0 + s_gate) if U == 2 else unit
            opts.append((cost, w, band, U))
        # For each U=2 option, find the cheapest U=1 option matching its
        # recovery, and say which is cheaper.
        for cost, w, band, U in sorted(opts):
            if U != 2:
                continue
            match = [(c1, w1, b1) for c1, w1, b1, u1 in opts
                     if u1 == 1 and w1 >= w]
            if not match:
                note = "no U=1 band here reaches this recovery"
            else:
                c1, w1, b1 = min(match)
                note = ("U=1 needs band=%d at cost %.0f -> %s"
                        % (b1, c1,
                           "U=2 cheaper by %.2fx" % (c1 / cost) if c1 > cost
                           else "U=1 cheaper by %.2fx" % (cost / c1)))
            print("    band=%-4d U=2  %-10.0f %-10.4f %s" % (band, cost, w, note))
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
