#!/usr/bin/env python3
"""Reproduce execution-contract findings from docs/execution-audit.md.

Diagnostic only: prints observations, without editing calibration or kernels.
Run with the installed matchedfilter package and a usable GPU for GPU checks.
"""
import argparse
import json
import numpy as np
import matchedfilter as mf


def run(device, repeats):
    results = {}
    n = 1024
    for label, frequency, gate in [('empty_coarse_band', 300, 0.),
                                    ('coarse_equality', 0, 1.)]:
        bank = np.zeros((1, n), np.complex64)
        bank[0, frequency] = 1
        rows = {}
        for dev in ['cpu', device]:
            f = mf.HierarchicalFilter(n, band=256, device=dev)
            f.set_coarse_threshold(gate)
            f.set_data(bank)
            f.set_templates(bank)
            out = f.run()
            rows[dev] = dict(index=int(out['index'].item()),
                             magnitude=float(np.abs(out['value']).item()),
                             stats=list(f.stats))
        results[label] = rows

    bank = np.ones((1, n), np.complex64)
    data = np.exp(-2j*np.pi*37*np.arange(n)/n).astype(np.complex64)[None, :]
    rows = {}
    for dev in ['cpu', device]:
        f = mf.MatchedFilter(n, device=dev)
        f.set_data(data)
        f.set_templates(bank)
        rows[dev] = {}
        for bs in [n, 2**32, 2**32+1]:
            out = f.run(binsize=bs, threshold=500)
            rows[dev][str(bs)] = dict(index=int(out['index'].item()),
                                      magnitude=float(np.abs(out['value']).item()))
    results['large_binsize'] = rows

    # Every lag is a true magnitude tie, but index and complex value must
    # describe the SAME lag. Checking only magnitude misses this race.
    n = 16384
    bank = np.zeros((32, n), np.complex64)
    bank[:, n//4] = 1
    f = mf.MatchedFilter(n, 32, 32, device=device)
    f.set_data(bank)
    f.set_templates(bank)
    mismatches = 0
    example = None
    phases = np.array([1, 1j, -1, -1j], np.complex64)
    for _ in range(repeats):
        out = f.run()
        expected = phases[out['index'] % 4]
        wrong = np.abs(out['value'] - expected) > 1e-5
        mismatches += int(np.count_nonzero(wrong))
        if example is None and wrong.any():
            row = tuple(np.argwhere(wrong)[0])
            example = dict(index=int(out['index'][row]),
                           actual=str(out['value'][row]), expected=str(expected[row]))
    results['tied_peak_value'] = dict(mismatches=mismatches,
                                     tested=repeats*32*32, example=example)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', default='gpu')
    parser.add_argument('--repeats', type=int, default=12)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    print(json.dumps(run(args.device, args.repeats), indent=2))


if __name__ == '__main__':
    main()
