#!/usr/bin/env python3
"""Tune the whole first-stage configuration by running the real filter.

Not a model.  An earlier version of this re-derived the statistic in numpy and
Monte-Carloed that, and it was wrong in the way re-derivations are wrong: it
reported a measured false dismissal of 0.0 for band 256 at U=1 -- a
configuration the captures show triggering 60% of the time, and which misses
244 of 842 triggers.  Anything that does not run the code cannot be trusted to
tune the code.

So every candidate here is built as an actual HierarchicalFilter with that
(band, oversample, taps), handed the same reference and bank, and run against
injections.  The ungated MatchedFilter on the same data is the truth, exactly
as tools/hier_bench.py does it, and a dismissal is a peak the flat filter
reports that the hierarchical one does not.  Cost is wall time of the same
call, not a formula.

The consequence worth having: after any change to the kernel or the gate, this
can be re-run and will say whether the compiled choices still hold.

    python tools/hmf_tune.py --n 4096 --snr 5.0 --fd 1e-3 --trials 4000
"""
import argparse
import sys
import time

import numpy as np

sys.path.insert(0, "tests")
from test_api import (inspiral_power, template_with_power, noise)  # noqa: E402
import matchedfilter as mf                                    # noqa: E402


def measure(n, band, U, K, snr, trials, seed=13, batch=64, power=None):
    """Measured (dismissal, seconds-per-pair) for one configuration.

    Both numbers come from the real filter.  Injections go into a batch of
    data spectra at once, which is how a caller drives it, so the time is
    throughput rather than per-call overhead, and the trial count needed to
    resolve 1e-4 stays affordable.
    """
    rng = np.random.default_rng(seed)
    if power is None:
        power = inspiral_power(n)
    power = np.ascontiguousarray(power, dtype=np.float32)
    # The statistic's distribution is fixed by how the SNR accumulates with
    # frequency, which is what the reference states.  A template whose own
    # power equals the reference reproduces that accumulation exactly, so it
    # stands in for any bank with the same profile -- including a ratio filter
    # whose own spectrum looks nothing like its output.
    H = template_with_power(n, power)
    flat = mf.MatchedFilter(n, ndata=batch, ntemplates=1)
    hf = mf.HierarchicalFilter(n, ndata=batch, ntemplates=1, snr=snr, fd=1e-3,
                               band=band, oversample=U, taps=K)
    hf.set_reference(power)
    flat.set_templates(H[None, :])
    hf.set_templates(H[None, :])

    detected = omitted = 0
    sec = 0.0
    npair = 0
    ph = np.exp(2j * np.pi * np.arange(n) / n)
    lag0 = 0
    for _ in range((trials + batch - 1) // batch):
        D = noise((batch, n), rng)
        for j in range(batch):
            lag0 = (lag0 + 37) % n
            D[j] += (snr * H * ph ** lag0).astype(np.complex64)
        flat.set_data(D)
        hf.set_data(D)
        a_ = flat.run(binsize=n, threshold=snr, raw=True)
        t0 = time.perf_counter()
        b_ = hf.run(binsize=n, threshold=snr, raw=True)
        sec += time.perf_counter() - t0
        npair += batch
        ai = np.array(a_[0])[:, 0, 0]
        bi = np.array(b_[0])[:, 0, 0]
        hit = ai >= 0
        detected += int(hit.sum())
        omitted += int((bi[hit] < 0).sum())
    return (omitted / detected if detected else 1.0), detected, sec / npair


def tune(n, snr, fd, trials=1500, seed=13, bands=None, verbose=True,
         power=None):
    if bands is None:
        bands = [b for b in (256, 512, 1024, 2048, 4096) if b <= n // 2]
    rows = []
    for band in bands:
        for U in (1, 2):
            for K in (4, 8):
                try:
                    dm, det, sec = measure(n, band, U, K, snr, trials, seed,
                                           power=power)
                except Exception as e:                       # unsupported combo
                    if verbose:
                        print("  band %-5d U=%d K=%-3d  unavailable (%s)"
                              % (band, U, K, e))
                    continue
                ok = dm <= fd
                rows.append(dict(band=band, U=U, K=K, dismissal=dm,
                                 detected=det, sec=sec, ok=ok))
                if verbose:
                    print("  band %-5d U=%d K=%-3d  dismissed %.3e of %-6d "
                          "%8.3f us/pair  %s" % (band, U, K, dm, det, sec * 1e6,
                                            "OK" if ok else "REJECT"))
    live = [r for r in rows if r["ok"]]
    return (min(live, key=lambda r: r["sec"]) if live else None), rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--snr", type=float, default=5.0)
    ap.add_argument("--fd", type=float, default=1e-3)
    ap.add_argument("--trials", type=int, default=1500)
    a = ap.parse_args()
    print("n=%d snr=%.1f fd=%.0e -- every row is the real filter, not a model\n"
          % (a.n, a.snr, a.fd))
    best, _ = tune(a.n, a.snr, a.fd, trials=a.trials)
    print("\nPICK: %s" % (best if best else "nothing met the target"))


if __name__ == "__main__":
    main()
