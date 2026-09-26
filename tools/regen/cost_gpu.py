"""Retune GPU relative costs with the current profile gate at each FDR.

The table ranks bands; gate accuracy always comes from the profile model.
Each cell is timed through the warm public API (including GPU readback), with
alternating order and block medians. Two matched profiles and two batch shapes
supply separate cost rows. Run on an otherwise idle GPU and inspect the retained
JSON measurements before shipping a table.

Run: OPENBLAS_NUM_THREADS=1 PYTHONPATH=python python tools/regen/cost_gpu.py \
  --out python/matchedfilter/cost-gfx11.txt --measurements docs/measurements/gpu-cost.json
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import matchedfilter as mf

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'tests'))
sys.path.insert(0, str(HERE.parent))
import hmf_tune as tuner
from test_api import inspiral_power


def _parse_ints(value):
    return [int(x) for x in value.split(',')]


def _parse_floats(value):
    return [float(x) for x in value.split(',')]


def _bank(power, ntemplates, seed):
    rng = np.random.default_rng(seed)
    phase = rng.random((ntemplates, len(power)), dtype=np.float32)
    spectra = (np.sqrt(power, dtype=np.float32)[None, :] *
               np.exp((2j * np.pi * phase).astype(np.complex64))).astype(np.complex64)
    spectra /= np.linalg.norm(spectra, axis=1, keepdims=True)
    return spectra


def _measure_group(n, snr, fd, exponent, nd, nt, bands, rounds):
    if exponent == 'pycbc':
        if n != 4096:
            raise ValueError('the pycbc reference asset has n=4096')
        power = np.load(HERE.parents[1] / 'tests' / 'data' /
                        'reference_profile_pycbc.npy')
    else:
        power = np.asarray(inspiral_power(n, exponent=exponent), dtype=np.float32)
    h = _bank(power, nt, 19)
    rng = np.random.default_rng(1)
    d = (rng.standard_normal((nd, n)) + 1j*rng.standard_normal((nd, n))).astype(np.complex64)
    plans = []
    try:
        for band in bands:
            f = mf.HierarchicalFilter(n, nd, nt, snr=snr, fd=fd,
                                       band=band, taps=4, device='gpu')
            plans.append((band, f))
            f.set_reference(power)
            f.set_data(d)
            f.set_templates(h)
            f.run(binsize=n, threshold=snr)
        samples = {band: [] for band in bands}
        for round_number in range(rounds):
            offset = round_number % len(plans)
            order = plans[offset:] + plans[:offset]
            if round_number % 2:
                order = order[::-1]
            for band, f in order:
                # Warm each configuration immediately before its timing block.
                until = time.perf_counter() + .05
                while time.perf_counter() < until:
                    f.run(binsize=n, threshold=snr)
                start = time.perf_counter()
                count = 0
                while time.perf_counter() - start < .05:
                    f.run(binsize=n, threshold=snr)
                    count += 1
                samples[band].append((time.perf_counter()-start)*1000/count)
        rows = []
        for band, f in plans:
            frac, beff = mf._band_features(power, band)
            rows.append(dict(n=n, snr=snr, fd=fd, exponent=exponent,
                             ndata=nd, ntemplates=nt, band=band,
                             ms=float(np.median(samples[band])),
                             blocks_ms=samples[band], fraction=frac, beff=beff,
                             refine_rate=f.refine_rate,
                             gate=f._gpu_calibration(snr)[2]))
        return rows
    finally:
        for _, f in plans:
            if f._gpu is not None:
                f._gpu.destroy()


def _write_table(path, records, device, commit, shapes, profiles):
    by_cell = {}
    for row in records:
        group = (row['n'], row['snr'], row['fd'], row['exponent'],
                 row['ndata'], row['ntemplates'])
        by_cell.setdefault(group, {})[row['band']] = row
    lines = [
        '# matchedfilter GPU COST table -- budget-aware relative costs',
        '# format cost-fd-pairs-v1',
        '# device  %s' % device,
        '# commit  %s' % commit,
        '# Profiles: %s; batch shapes: %s' % (profiles, shapes),
        '# Costs are warm public-API ratios to the widest band at the same batch shape.',
        '# Accuracy is independent and uses the profile gate.',
        '# U=2; taps K are metadata on this GPU, so K=4 and K=8 share costs.',
        '# COST n band U K snr fd pairs f beff relative_cost',
    ]
    for group in sorted(by_cell, key=lambda v: tuple(map(str, v))):
        bands = by_cell[group]
        base = bands[max(bands)]['ms']
        if base <= 0:
            raise ValueError('zero pivot time')
        for band in sorted(bands):
            row = bands[band]
            rel = row['ms']/base
            pairs = row['ndata']*row['ntemplates']
            for k in (4, 8):
                lines.append('COST %d %d 2 %d %.2f %.6g %d %.6f %.3f %.6f' %
                             (row['n'], band, k, row['snr'], row['fd'], pairs,
                              row['fraction'], row['beff'], rel))
    path.write_text('\n'.join(lines)+'\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--measurements', type=Path)
    ap.add_argument('--sizes', type=_parse_ints, default=[1024, 2048, 4096, 8192, 16384])
    ap.add_argument('--snrs', type=_parse_floats, default=[5., 5.5, 6., 6.5])
    ap.add_argument('--fds', type=_parse_floats, default=[.01, .001, .0001])
    ap.add_argument('--profiles', type=_parse_floats, default=[-7/3, -2.])
    ap.add_argument('--shapes', default='16x256,16x1024')
    ap.add_argument('--rounds', type=int, default=5)
    ap.add_argument('--repair-outliers', action='store_true',
                    help='resume recorded measurements and remeasure groups with >25%% timing spread')
    ap.add_argument('--include-pycbc', action='store_true',
                    help='also measure the real n=4096 pycbc reference profile')
    args = ap.parse_args(argv)
    shapes = [tuple(map(int, s.split('x'))) for s in args.shapes.split(',')]
    if args.rounds < 3 or any(nd < 1 or nt < 1 for nd, nt in shapes):
        ap.error('need >=3 rounds and positive shapes')
    devices = [d for d in mf.devices() if d.kind == 'gpu' and not d.is_software]
    if not devices:
        ap.error('no hardware GPU')
    dev = devices[0]
    key = dev.arch[1] if len(dev.arch) > 1 else (dev.arch or ['gpu'])[0]
    args.out = args.out or Path(mf.__file__).resolve().parent / ('cost-%s.txt' % key)
    args.measurements = args.measurements or Path('docs/measurements') / (
        'gpu-cost-%s.json' % key)
    try:
        commit = subprocess.check_output(['git','rev-parse','--short','HEAD'],
                                         text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        commit = 'unknown'
    records = []
    if args.repair_outliers:
        records = json.loads(args.measurements.read_text())['records']
        groups = {}
        for row in records:
            group = (row['n'], row['snr'], row['fd'], row['exponent'],
                     row['ndata'], row['ntemplates'])
            groups.setdefault(group, []).append(row)
        redo = [group for group, rows in groups.items()
                if any(max(row['blocks_ms'])/min(row['blocks_ms']) > 1.25
                       for row in rows)]
        if args.include_pycbc and 4096 in args.sizes:
            redo.extend((4096, snr, fd, 'pycbc', nd, nt)
                        for snr in args.snrs for fd in args.fds
                        for nd, nt in shapes
                        if (4096, snr, fd, 'pycbc', nd, nt) not in groups)
        for group in redo:
            n, snr, fd, exponent, nd, nt = group
            bands = [band for band in tuner.bands_for(n) if band < n]
            rows = _measure_group(*group, bands, args.rounds)
            records = [row for row in records if (row['n'], row['snr'], row['fd'],
                row['exponent'], row['ndata'], row['ntemplates']) != group]
            records.extend(rows)
            args.measurements.write_text(json.dumps(dict(
                device=dev.name, commit=commit, records=records), indent=2)+'\n')
            print('remeasured n=%d snr=%g fd=%g profile=%s shape=%dx%d' %
                  group, flush=True)
        _write_table(args.out, records, dev.name, commit, shapes,
                     args.profiles + (['pycbc'] if args.include_pycbc else []))
        print('wrote', args.out, flush=True)
        return 0
    for n in args.sizes:
        bands = [band for band in tuner.bands_for(n) if band < n]
        for snr in args.snrs:
            for fd in args.fds:
                profiles = args.profiles + (['pycbc'] if args.include_pycbc and n == 4096 else [])
                for exponent in profiles:
                    for nd, nt in shapes:
                        rows = _measure_group(n,snr,fd,exponent,nd,nt,bands,args.rounds)
                        records.extend(rows)
                        print('n=%d snr=%g fd=%g exponent=%s shape=%dx%d best=%d' %
                              (n,snr,fd,exponent,nd,nt,min(rows,key=lambda r:r['ms'])['band']),
                              flush=True)
                        args.measurements.parent.mkdir(parents=True,exist_ok=True)
                        args.measurements.write_text(json.dumps(dict(
                            device=dev.name, commit=commit, records=records),indent=2)+'\n')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    _write_table(args.out, records, dev.name, commit, shapes,
                 args.profiles + (['pycbc'] if args.include_pycbc else []))
    print('wrote',args.out,flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
