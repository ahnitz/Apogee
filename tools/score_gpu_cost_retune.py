"""Score an 8060S cost retune against the retained family table.

Every measured band in the input was run with its own model gate. This scores
only configuration ranking, never accuracy, and retains case-level results.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
import matchedfilter as mf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_api import inspiral_power


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--measurements', type=Path, required=True)
    ap.add_argument('--new', type=Path, required=True)
    ap.add_argument('--old', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    records = json.loads(args.measurements.read_text())['records']
    new = mf._load_tuning(str(args.new))
    old = mf._load_tuning(str(args.old))
    groups = {}
    for row in records:
        key = (row['n'],row['snr'],row['fd'],row['exponent'],
               row['ndata'],row['ntemplates'])
        groups.setdefault(key,{})[row['band']] = row['ms']
    cases = []
    for key, times in groups.items():
        n,snr,fd,profile,nd,nt = key
        power = (np.load(Path(__file__).resolve().parents[1] / 'tests' /
                         'data' / 'reference_profile_pycbc.npy')
                 if profile == 'pycbc' else
                 inspiral_power(n, exponent=profile).astype(np.float32))
        new_band = mf._cost_candidates(power,n,snr,new,fd,nd*nt)[0]['band']
        old_band = mf._cost_candidates(power,n,snr,old,fd,nd*nt)[0]['band']
        fastest = min(times,key=times.get)
        if new_band not in times or old_band not in times:
            raise ValueError('table selected an unmeasured band: %s' % (key,))
        cases.append(dict(n=n,snr=snr,fd=fd,profile=profile,ndata=nd,ntemplates=nt,
                          fastest=fastest,new_band=new_band,old_band=old_band,
                          best_ms=times[fastest],new_ms=times[new_band],old_ms=times[old_band],
                          new_regret=times[new_band]/times[fastest],
                          old_regret=times[old_band]/times[fastest],
                          new_vs_old=times[new_band]/times[old_band]))
    ratios = np.array([c['new_vs_old'] for c in cases])
    summary = dict(cases=len(cases), median_new_vs_old=float(np.median(ratios)),
                   geometric_mean_new_vs_old=float(np.exp(np.log(ratios).mean())),
                   faster_5pct=int(np.sum(ratios<.95)),
                   slower_5pct=int(np.sum(ratios>1.05)),
                   worst_regression=max(cases,key=lambda c:c['new_vs_old']),
                   largest_gain=min(cases,key=lambda c:c['new_vs_old']))
    result = dict(summary=summary,cases=cases)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
