"""Merge the benchmark matrix into a table and a plot.

Reads m_{avx512,avx2}_{quiet,load}.csv written by bench4, whose columns are
N,mkl,sysfftw,amdfftw,apogee (seconds, minimum over blocks).
"""
import csv, json, os, sys
import numpy as np

def load(tag):
    f = f"m_{tag}.csv"
    if not os.path.exists(f):
        return None
    return {int(r["N"]): {k: float(v) for k, v in r.items() if k != "N"}
            for r in csv.DictReader(open(f))}

sets = {t: load(t) for t in ("avx512_quiet", "avx2_quiet", "avx512_load", "avx2_load")}
have = {k: v for k, v in sets.items() if v}
if not have:
    sys.exit("no csv files yet")
json.dump({k: {str(n): d for n, d in v.items()} for k, v in have.items()},
          open("matrix.json", "w"), indent=1)

for regime in ("quiet", "load"):
    a, b = sets.get(f"avx512_{regime}"), sets.get(f"avx2_{regime}")
    if not a:
        continue
    print(f"\n=== {regime} ===")
    print(f"{'N':>7} {'MKL':>9} {'FFTW':>9} {'amdFFTW':>9} {'pf512':>9} {'pf-avx2':>9} "
          f"| {'vs MKL':>7} {'vs FFTW':>8} {'vs AMD':>7}")
    for n in sorted(a):
        r = a[n]
        p2 = b[n]["apogee"] * 1e6 if b and n in b else float("nan")
        u = 1e6
        print(f"2^{n.bit_length()-1:<5d} {r['mkl']*u:8.2f} {r['sysfftw']*u:8.2f} "
              f"{r['amdfftw']*u:8.2f} {r['apogee']*u:8.2f} {p2:8.2f} "
              f"| {r['mkl']/r['apogee']:6.2f}x {r['sysfftw']/r['apogee']:7.2f}x "
              f"{r['amdfftw']/r['apogee']:6.2f}x")
