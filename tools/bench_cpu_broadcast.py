#!/usr/bin/env python3
"""Compare isolated package builds with alternating persistent worker processes.

Example: python tools/bench_cpu_broadcast.py /tmp/old /tmp/new --output result.json
Each directory must contain a matchedfilter package, including its native module.
No calibration table is used: hierarchical thresholds select a measured fraction
of these seeded noise pairs, and output bytes must match between builds.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time


def worker():
    import numpy as np
    import matchedfilter as mf
    plans = {}
    for line in sys.stdin:
        cfg = json.loads(line)
        band, nt, kind, survival, cutoff, ingest = cfg[:6]
        key = tuple(cfg[:6])
        if key not in plans:
            rng = np.random.default_rng(band + nt)
            def noise(shape):
                return (rng.normal(size=shape) + 1j*rng.normal(size=shape)).astype('complex64')
            n = 4096 if kind == 'hier' else band
            if kind == 'hier':
                f = mf.HierarchicalFilter(n, 8, nt, band=band, snr=5.5, fd=.01)
                f.set_coarse_threshold(0.)
            else:
                f = mf.MatchedFilter(n, 8, nt)
            h, d = noise((nt, n)), noise((8, n))
            f.set_templates(h)
            f.set_data(d)
            if kind == 'hier':
                coarse = mf.MatchedFilter(band, 8, nt)
                power = abs(h.astype(np.complex128))**2
                fraction = power[:, :band].sum(axis=1)/power.sum(axis=1)
                coarse.set_templates((h[:, :band]/np.sqrt(fraction[:, None])).astype('complex64'))
                coarse.set_data(d[:, :band].copy())
                maxima = np.abs(coarse.run(binsize=band)['value'])
                threshold = (float(np.quantile(maxima, 1-survival))
                             if survival > 0 else 1e10)
                f.set_coarse_threshold(threshold)
            kw = dict(binsize=n, raw=True)
            out = f.run(**kw)
            digest = hashlib.sha256(b''.join(x.tobytes() for x in out)).hexdigest()
            admitted = float((out[0] >= 0).mean())
            plans[key] = f, kw, digest, admitted, h, d
        f, kw, digest, admitted, h, d = plans[key]
        f.run(**kw)
        t = time.perf_counter()
        for _ in range(cfg[6]):
            if ingest:
                f.set_templates(h)
                f.set_data(d)
            f.run(**kw)
        print(json.dumps([(time.perf_counter()-t)/cfg[6], digest, admitted]), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline')
    p.add_argument('candidate')
    p.add_argument('--output', required=True)
    p.add_argument('--isas', nargs='+', default=['AVX3', 'AVX2', 'SSE4'])
    p.add_argument('--bands', nargs='+', type=int, default=[64, 128, 256, 512, 1024])
    p.add_argument('--templates', nargs='+', type=int, default=[1, 16, 37, 128])
    p.add_argument('--kinds', nargs='+', choices=['flat', 'hier'], default=['flat', 'hier'])
    p.add_argument('--survival', type=float, default=.01)
    p.add_argument('--rounds', type=int, default=9)
    p.add_argument('--cutoff', type=int, default=1024, help='MF_PBMAX; 0 uses automatic dispatch')
    p.add_argument('--include-ingest', action='store_true')
    args = p.parse_args()
    results = []
    for isa in args.isas:
        workers = []
        try:
            for root in (args.baseline, args.candidate):
                env = dict(os.environ, PYTHONPATH=str(Path(root).resolve()), MF_ISA=isa)
                env.pop('MF_PBMAX', None)
                if args.cutoff:
                    env['MF_PBMAX'] = str(args.cutoff)
                workers.append(subprocess.Popen(
                    [sys.executable, str(Path(__file__).resolve()), '--worker'],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env))
            for kind in args.kinds:
                for band in args.bands:
                    for nt in args.templates:
                        cfg = [band, nt, kind, args.survival, args.cutoff,
                               args.include_ingest, max(50, 20000//nt)]
                        times, digests, admitted = [[], []], set(), set()
                        for round_ in range(args.rounds):
                            for i in ((0, 1) if round_ % 2 == 0 else (1, 0)):
                                workers[i].stdin.write(json.dumps(cfg)+'\n')
                                workers[i].stdin.flush()
                                line = workers[i].stdout.readline()
                                if not line:
                                    raise RuntimeError(f'{isa}: worker {i} exited')
                                seconds, digest, rate = json.loads(line)
                                times[i].append(seconds)
                                digests.add(digest)
                                admitted.add(rate)
                        if len(digests) != 1:
                            raise AssertionError(f'Output mismatch: {isa}, {cfg}')
                        row = dict(isa=isa, band=band, templates=nt, kind=kind,
                                   cutoff=args.cutoff, ingest=args.include_ingest,
                                   admitted=sorted(admitted), samples=times,
                                   speedup=statistics.median([a/b for a, b in zip(*times)]))
                        results.append(row)
                        Path(args.output).write_text(json.dumps(results, indent=2)+'\n')
                        print(f'{isa} {kind} band={band} templates={nt}: {row["speedup"]:.3f}x', flush=True)
        finally:
            for proc in workers:
                proc.stdin.close()
                proc.wait()


if __name__ == '__main__':
    if sys.argv[1:] == ['--worker']:
        worker()
    else:
        main()
