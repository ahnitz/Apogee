"""Compare GPU coarse bands at fixed accuracy budgets on the teaser workload.

Run on a quiet machine. Every band uses its own profile-model gate. Alternate
measurement order to reduce clock/order bias; no measured gate is relaxed.
The output includes all block samples, refinement rates and chosen gates.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
import matchedfilter as mf
import teaser_figure as teaser


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bands', nargs='+', type=int, default=[128, 256, 512, 1024])
    ap.add_argument('--fd', nargs='+', type=float, default=[.01, .001, .0001])
    ap.add_argument('--rounds', type=int, default=9)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    if args.rounds < 3:
        ap.error('at least three rounds are required')
    d, h = teaser._case()
    ref, _ = teaser._reference()
    report = dict(n=teaser.N, data=teaser.ND, templates=teaser.NT, snr=5.5,
                  device=teaser._gpu_name(), rows=[])
    for fd in args.fd:
        plans = []
        try:
            for band in args.bands:
                f = mf.HierarchicalFilter(teaser.N, teaser.ND, teaser.NT,
                    snr=5.5, fd=fd, band=band, device='gpu')
                plans.append((band, f))
                f.set_reference(ref)
                f.set_data(d)
                f.set_templates(h)
                f.run(binsize=teaser.N, threshold=5.5)
            samples = {band: [] for band in args.bands}
            for round_number in range(args.rounds):
                offset = round_number % len(plans)
                order = plans[offset:] + plans[:offset]
                if round_number % 2:
                    order = order[::-1]
                for band, f in order:
                    until = time.perf_counter() + .15
                    while time.perf_counter() < until:
                        f.run(binsize=teaser.N, threshold=5.5)
                    start = time.perf_counter()
                    count = 0
                    while time.perf_counter() - start < .08:
                        f.run(binsize=teaser.N, threshold=5.5)
                        count += 1
                    samples[band].append((time.perf_counter()-start)*1000/count)
            for band, f in plans:
                values = samples[band]
                row = dict(fd=fd, band=band, ms=float(np.median(values)),
                           block_ms=values, refine_rate=f.refine_rate,
                           gate=f._gpu_calibration(5.5)[2])
                report['rows'].append(row)
                print(json.dumps(row), flush=True)
        finally:
            for _, f in plans:
                if f._gpu is not None:
                    f._gpu.destroy()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
