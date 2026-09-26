"""Independent holdout workloads for the 8060S cost-table retune.

The profile exponent and batch shapes below do not occur in the training
measurements. Each candidate uses its own model gate at the requested FDR.
Score the JSON with tools/score_gpu_cost_retune.py.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'regen'))
import cost_gpu


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--rounds', type=int, default=7)
    args = ap.parse_args()
    cases = [(4096, 5.5, (.01, .001, .0001)),
             (8192, 6., (.001, .0001)),
             (16384, 6.5, (.0001,))]
    shapes = [(8,512), (16,512)]
    rows = []
    for n, snr, fds in cases:
        bands = [b for b in cost_gpu.tuner.bands_for(n) if b < n]
        for fd in fds:
            for nd, nt in shapes:
                measured = cost_gpu._measure_group(n,snr,fd,-5/3,nd,nt,bands,args.rounds)
                rows.extend(measured)
                print('n=%d snr=%g fd=%g shape=%dx%d best=%d' %
                      (n,snr,fd,nd,nt,min(measured,key=lambda r:r['ms'])['band']),
                      flush=True)
                args.out.parent.mkdir(parents=True,exist_ok=True)
                args.out.write_text(json.dumps(dict(records=rows),indent=2)+'\n')


if __name__ == '__main__':
    main()
