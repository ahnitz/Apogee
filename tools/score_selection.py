#!/usr/bin/env python3
"""Compare the selected configuration with measured admissible alternatives.

Uses the library's ACC2 admission rules. Older accuracy-table generations
are reported as unsupported rather than silently scored as empty.
"""
import argparse
import time
import numpy as np
import matchedfilter as mf
from matchedfilter.benchmark import _inspiral_power
from score_cost_rule import admissible


def score(n, snr, nd=8, nt=32, fd=1e-3):
    power = _inspiral_power(n)
    candidates = admissible(power, n, snr, fd, mf._load_tuning())
    if candidates is None:
        raise ValueError(f"n={n}, snr={snr}: no ACC2 coverage; legacy scoring unsupported")
    pick = mf.choose_config(power, n, snr, fd)
    rng = np.random.default_rng(7)
    h = (np.sqrt(power)*np.exp(1j*rng.uniform(0, 2*np.pi, (nt,n)))).astype(np.complex64)
    h /= np.sqrt((np.abs(h)**2).sum(axis=1, keepdims=True))
    d = (rng.normal(size=(nd,n))+1j*rng.normal(size=(nd,n))).astype(np.complex64)
    window = (int(.2*n)&~15, int(.8*n)&~15)
    def elapsed(f):
        f.run(binsize=n, threshold=snr, window=window)
        samples=[]
        for _ in range(5):
            start=time.perf_counter()
            for _ in range(10):
                f.run(binsize=n, threshold=snr, window=window)
            samples.append((time.perf_counter()-start)/10)
        return float(np.median(samples))
    flat=mf.MatchedFilter(n, nd, nt)
    flat.set_data(d); flat.set_templates(h)
    baseline=elapsed(flat)
    timings={}
    configs={(c[0],c[2]) for c in candidates}
    if pick is not None:
        configs.add(tuple(pick))
    for band,taps in sorted(configs):
        f=mf.HierarchicalFilter(n,nd,nt,snr,fd,band=band,taps=taps)
        f.set_reference(power); f.set_data(d); f.set_templates(h)
        timings[(band,taps)]=baseline/elapsed(f)
    if not timings:
        return pick, None, None, None
    best=max(timings,key=timings.get)
    selected=1.0 if pick is None else timings[tuple(pick)]
    return pick,best,selected,timings[best]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--n',type=int,default=4096)
    ap.add_argument('--snr',type=float,default=6.)
    a=ap.parse_args()
    try:
        pick,best,got,fastest=score(a.n,a.snr)
    except ValueError as exc:
        ap.error(str(exc))
    if best is None:
        print('No admissible hierarchical configurations; flat fallback.')
    else:
        print(f'picked {pick}: {got:.2f}x; best {best}: {fastest:.2f}x; {100*got/fastest:.0f}% of best')


if __name__ == '__main__':
    main()
