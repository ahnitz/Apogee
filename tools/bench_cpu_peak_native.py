#!/usr/bin/env python3
"""Compare native CPU peak kernels across several live scratch-buffer layouts.

BASE and CAND contain built matchedfilter packages for this Python version.
Requires an AVX2-capable x86 CPU and an installed matchedfilter package. The
native timing bridge is reused from narrow_cpu. Forces pair batching, compares
every output field, and excludes ingestion and Python call overhead.
"""
import argparse
import ctypes as C
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sysconfig

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--bands', nargs='+', type=int, default=[64, 128, 512, 1024])
    parser.add_argument('--templates', nargs='+', type=int, default=[1, 16, 128])
    parser.add_argument('--isas', nargs='+', default=['AVX3', 'AVX2', 'SSE4'])
    parser.add_argument('--rounds', type=int, default=9)
    parser.add_argument('--layouts', type=int, default=5)
    parser.add_argument('--repeats', type=int, default=200)
    args = parser.parse_args()
    if min(args.rounds, args.layouts, args.repeats, *args.templates) < 1:
        parser.error('rounds, layouts, repeats and template counts must be positive')

    study_path = Path(__file__).with_name('narrow_cpu') / 'run.py'
    spec = importlib.util.spec_from_file_location('narrow', study_path)
    study = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(study)
    available = set(study._core.targets())
    if 'AVX2' not in available:
        parser.error('the native timing bridge requires an AVX2-capable CPU')
    build = Path('/tmp/mf-cpu-peak-native')
    build.mkdir(parents=True, exist_ok=True)
    bridge = study.build('avx2', build)
    roots = (args.baseline, args.candidate)
    os.environ['MF_PBMAX'] = '1024'
    results = []
    suffix = sysconfig.get_config_var('EXT_SUFFIX')
    for isa in args.isas:
        if isa not in available:
            parser.error(f'{isa} is unavailable on this host')
        for n in args.bands:
            for nt in args.templates:
                rng = np.random.default_rng(n + nt)
                h, d = study.noise(rng, (nt, n)), study.noise(rng, (8, n))
                plans, allocated = [], []
                try:
                    # Keep all plans alive to sample several scratch placements;
                    # reverse allocation order as well as timing order.
                    for layout in range(args.layouts):
                        pair = [None, None]
                        for i in ((0, 1) if layout % 2 == 0 else (1, 0)):
                            path = str(roots[i] / 'matchedfilter' / ('_core' + suffix))
                            lib = C.CDLL(path)
                            study.bind(lib, 'ap_set_target', [C.c_char_p], C.c_int)
                            if lib.ap_set_target(isa.encode()) != 0:
                                raise RuntimeError(f'{isa} unavailable in {path}')
                            p = study.Reference(bridge, n, 8, nt, core_path=path)
                            allocated.append(p)
                            p.templates(h)
                            p.data(d)
                            p.run()
                            pair[i] = p
                        for field in ('index', 're', 'im', 'magnitude'):
                            np.testing.assert_array_equal(pair[0].out[field], pair[1].out[field])
                        plans.append(pair)
                    samples = []
                    for round_ in range(args.rounds):
                        for layout, pair in enumerate(plans):
                            t = [0., 0.]
                            for i in ((0, 1) if round_ % 2 == 0 else (1, 0)):
                                t[i] = pair[i].bench(args.repeats, 0)
                            samples.append(dict(layout=layout, round=round_,
                                                baseline=t[0], candidate=t[1]))
                    ratios = [statistics.median(s['baseline'] / s['candidate']
                              for s in samples if s['layout'] == layout)
                              for layout in range(args.layouts)]
                    results.append(dict(isa=isa, band=n, templates=nt,
                                        layout_speedups=ratios,
                                        speedup=statistics.median(ratios), samples=samples))
                    args.output.write_text(json.dumps(results, indent=2) + '\n')
                    print(isa, n, nt, [round(r, 3) for r in ratios], flush=True)
                finally:
                    for plan in allocated:
                        plan.close()


if __name__ == '__main__':
    main()
