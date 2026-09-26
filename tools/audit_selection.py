#!/usr/bin/env python3
"""Measure calibrated candidates on the requested device and batch shape.

This is an offline diagnostic. It never modifies shipped cost rows or chooses
an uncalibrated gate. Use its JSON report to review proposed cost-table changes.
"""
import argparse
import json
import time
import numpy as np
import matchedfilter as mf
from matchedfilter.benchmark import _inspiral_power


def candidate_coverage(power, n, snr, fd, tuning):
    """Report missing measurements as well as runnable measured candidates."""
    rows = []
    bands = [2**k for k in range(6, n.bit_length()-1)]
    for band in bands:
        costs = [key for source in (tuning['cost'], tuning.get('cost_fd', {}),
                                   tuning.get('cost_fd_pairs', {}))
                 for key in source if key[0] == n and key[1] == band]
        threshold = mf.choose_threshold(power, n, snr, fd, band)
        fraction, beff = mf._band_features(power, band)
        rows.append(dict(band=band, fraction=fraction, beff=beff,
                         cost_rows=len(costs), threshold=threshold,
                         runnable=threshold is not None))
    return rows


def audit(n=4096, snr=6., fd=1e-3, nd=8, nt=32, device='cpu', reps=7):
    rng = np.random.default_rng(7)
    power = _inspiral_power(n)
    flat = mf.MatchedFilter(n, nd, nt, device=device)
    tuning = mf._load_tuning() if flat.device.kind == 'cpu' else mf._load_tuning_for(flat.device)
    coverage = candidate_coverage(power, n, snr, fd, tuning)
    pick = mf.choose_config(power, n, snr, fd, tuning=tuning)
    h = (np.sqrt(power)*np.exp(1j*rng.uniform(0, 2*np.pi, (nt,n)))).astype(np.complex64)
    h /= np.linalg.norm(h, axis=1)[:, None]
    d = (rng.normal(size=(nd,n))+1j*rng.normal(size=(nd,n))).astype(np.complex64)
    window = (int(.2*n)&~15, int(.8*n)&~15)
    plans = {'flat': flat}
    for row in coverage:
        if not row['runnable']:
            continue
        # The raw coarse maximum has no tap interpolation. One representative
        # per band avoids timing identical executions under different labels.
        f = mf.HierarchicalFilter(n, nd, nt, snr, fd, band=row['band'], device=device)
        f.set_coarse_threshold(row['threshold'])
        f.set_reference(power)
        plans[str(row['band'])] = f
    for f in plans.values():
        f.set_templates(h)
        f.set_data(d)
        f.run(binsize=n, threshold=snr, window=window)
    samples = {key: [] for key in plans}
    keys = list(plans)
    for trial in range(reps):
        # Reverse each round to reduce ordering/temperature bias.
        for key in (keys if trial % 2 == 0 else keys[::-1]):
            begin = time.perf_counter()
            for _ in range(10):
                plans[key].run(binsize=n, threshold=snr, window=window)
            samples[key].append((time.perf_counter()-begin)/10)
    medians = {key: float(np.median(values)) for key, values in samples.items()}
    for row in coverage:
        key = str(row['band'])
        if key in medians:
            row.update(seconds=medians[key], speedup=medians['flat']/medians[key])
    best = min(medians, key=medians.get)
    selected_key = str(pick[0]) if pick else None
    return dict(n=n, snr=snr, fd=fd, data=nd, templates=nt, device=str(flat.device),
                selected=pick, fastest=best, flat_seconds=medians['flat'],
                selected_over_fastest=(medians[selected_key]/medians[best]
                                       if selected_key in medians else None),
                candidates=coverage)


def export_cost(result, path):
    """Reprice existing bands; new bands need separate accuracy validation.

    File lookup alone is not evidence that an unselected corner meets its
    budget. The small-band low-ratio defect is a concrete counterexample.
    """
    lines = ["# Measured by audit_selection.py; one reference and batch shape.",
             "# n=%d data=%d templates=%d device=%s" %
             (result['n'], result['data'], result['templates'], result['device']),
             "# Existing cost-covered bands only; new-band accuracy is not established.",
             "# Do not replace broad default coverage with this narrow measurement."]
    if str(result['device']).startswith('gpu'):
        lines.append('# format cost-fd-pairs-v1')
    header_lines = len(lines)
    for row in result['candidates']:
        if 'seconds' not in row or not row['cost_rows']:
            continue
        # Taps do not change the raw-max execution; retain both table keys.
        for taps in (4, 8):
            prefix = "COST %d %d 2 %d %.2f" % (
                result['n'], row['band'], taps, result['snr'])
            if str(result['device']).startswith('gpu'):
                prefix += " %.9g %d" % (result['fd'],
                                          result['data']*result['templates'])
            lines.append("%s %.9g %.9g %.9g" %
                         (prefix, row['fraction'], row['beff'],
                          row['seconds']/result['flat_seconds']))
    if len(lines) == header_lines:
        raise ValueError('no calibrated candidates were measured')
    with open(path, 'w') as stream:
        stream.write('\n'.join(lines)+'\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n', type=int, default=4096)
    parser.add_argument('--snr', type=float, default=6.)
    parser.add_argument('--fd', type=float, default=1e-3)
    parser.add_argument('--data', type=int, default=8)
    parser.add_argument('--templates', type=int, default=32)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--reps', type=int, default=7)
    parser.add_argument('--json')
    parser.add_argument('--cost-output', help='write measured rows for an explicit MF_COST override')
    args = parser.parse_args(argv)
    if min(args.data, args.templates, args.reps) < 1:
        parser.error('data, templates and reps must be positive')
    result = audit(args.n, args.snr, args.fd, args.data, args.templates, args.device, args.reps)
    if args.cost_output:
        export_cost(result, args.cost_output)
    output = json.dumps(result, indent=2)
    if args.json:
        with open(args.json, 'w') as stream:
            stream.write(output+'\n')
    print(output)


if __name__ == '__main__':
    main()
