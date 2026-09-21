#!/usr/bin/env python3
"""Compare two independently built copies of the library.

    python tools/compare_builds.py /tmp/env-ref/bin/python /tmp/env-hwy/bin/python

MF_ISA can only choose between back ends compiled into one extension.  Once a
branch stops building the others there is nothing to switch to, so comparing
against the previous implementation means running two builds side by side.

They cannot share a process -- both call themselves `matchedfilter` -- so each
runs as a subprocess and the two are interleaved round by round, which is what
keeps a drifting machine from being charged to one of them.  Peaks are
compared before any timing is reported.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile

# Runs inside each interpreter.  Kept in one string so the two builds execute
# byte-identical code and any difference is the library, not the harness.
WORKER = r'''
import json, os, sys, time
import numpy as np
import matchedfilter as mf

cfg = json.loads(sys.argv[1])
n, ntmpl, ntaps = cfg["n"], cfg["ntmpl"], cfg["ntaps"]
series_len, thresh, reps = cfg["series"], cfg["threshold"], cfg["reps"]
if cfg.get("isa"):
    os.environ["MF_ISA"] = cfg["isa"]

rng = np.random.default_rng(11)
k = np.arange(n)
power = np.zeros(n, np.float32)
power[1:n//2] = (k[1:n//2] ** (-7.0/3.0)).astype(np.float32)
power /= power.sum()
h = (np.sqrt(power) * np.exp(1j*rng.uniform(0, 2*np.pi, (ntmpl, n)))).astype(np.complex64)
h /= np.sqrt((np.abs(h)**2).sum(axis=1, keepdims=True))
series = ((rng.standard_normal(series_len) + 1j*rng.standard_normal(series_len))
          / np.sqrt(2)).astype(np.complex64)

# Inject signals so the comparison has peaks to compare.  On pure noise at
# this threshold nothing survives, and two builds agreeing that the answer is
# empty says very little -- it would not catch a reconstruction that is
# wrong, only one that fires when it should not.
# Injected copy, for the correctness pass only.  Timing runs on the noise
# series: the trigger rate is what decides how often the second stage runs,
# and a series full of loud injections is a different, much heavier workload
# than the one this is meant to represent.
namp = cfg.get("inject", 0.0)
loud = series.copy()
for j, pos in enumerate(np.linspace(0.05, 0.95, cfg["ninject"] if namp else 0)):
    t0 = int(pos * (series_len - n))
    # h is unit-norm in the FREQUENCY domain, so its inverse transform carries
    # a 1/n; normalise before scaling.  Without that, an amplitude of 40 sat
    # far below unit-variance noise, the correctness pass found nothing, and
    # the harness reported IDENTICAL over two empty results.
    w = np.fft.ifft(np.conj(h[j % ntmpl]))
    w /= np.linalg.norm(w)
    loud[t0:t0+n] += (namp * w).astype(np.complex64)

valid, bad = n - ntaps + 1, ntaps // 2
starts, ws, we, t = [], [], [], 0
while t + n <= series_len:
    starts.append(t); ws.append(bad); we.append(bad + valid); t += valid
starts = np.array(starts, np.uintp); ws = np.array(ws, np.uintp); we = np.array(we, np.uintp)

p = mf.HierarchicalFilter(n, ndata=1, ntemplates=ntmpl, snr=thresh, fd=1e-3,
                          band=cfg["band"], oversample=2, taps=8)
p.set_reference(power); p.set_templates(h)

# Correctness pass: first stage at the lowest level the design grid offers
# (hmf_threshold clamps to snr 4.5), and no threshold on the reported peaks,
# so as many pairs as possible are reconstructed and compared.  Lowering only
# the run_series threshold is not enough -- the first-stage level is floored
# by the plan's snr, so nothing fires and both builds agree the answer is
# empty, which would not catch a wrong reconstruction at all.
p.set_first_stage(0.01)
idx, val, mag = p.run_series(loud, starts, ws, we, binsize=n,
                             threshold=0.0, raw=True)
# run_series hands back the plan's own buffers, so this has to be copied
# before the timing runs below scribble over it.  Not copying it is how the
# fingerprint came from the noise pass instead of the injected one.
idx, mag = np.array(idx), np.array(mag)
p.set_first_stage(None)
# Timing pass at the real threshold, which is what decides how often the
# full reconstruction runs.
p.run_series(series, starts, ws, we, binsize=n, threshold=thresh, raw=True)
best = float("inf")
for _ in range(reps):
    t0 = time.perf_counter()
    p.run_series(series, starts, ws, we, binsize=n, threshold=thresh, raw=True)
    best = min(best, time.perf_counter() - t0)

print(json.dumps({
    "backend": mf.backend(),
    "ms": best * 1e3,
    "blocks": len(starts),
    "trigger_rate": p.trigger_rate,
    # a cheap fingerprint of the whole result, so a disagreement anywhere shows
    "idx_sum": int(np.asarray(idx, dtype=np.int64).sum()),
    "mag_sum": float(np.asarray(mag, dtype=np.float64).sum()),
    "mag_max": float(np.asarray(mag, dtype=np.float64).max()),
    "n_peaks": int((np.asarray(idx) >= 0).sum()),
}))
'''


def run(python, cfg):
    out = subprocess.run([python, "-c", WORKER, json.dumps(cfg)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("%s failed:\n%s" % (python, out.stderr[-2000:]))
    return json.loads(out.stdout.strip().split("\n")[-1])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("reference", help="interpreter with the build to beat")
    ap.add_argument("candidate", help="interpreter with the build under test")
    ap.add_argument("--rounds", type=int, default=5,
                    help="interleaved rounds (default 5)")
    ap.add_argument("--reps", type=int, default=5,
                    help="timed repeats within each round")
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--templates", type=int, default=64)
    ap.add_argument("--taps", type=int, default=1024)
    ap.add_argument("--series", type=int, default=1 << 20)
    ap.add_argument("--band", type=int, default=512)
    ap.add_argument("--threshold", type=float, default=5.5)
    ap.add_argument("--inject", type=float, default=2000.0,
                    help="amplitude of injected signals, so there are peaks "
                         "to compare (0 for pure noise).  Whitening makes the "
                         "recovered SNR a couple of orders of magnitude below "
                         "this; the run fails if the result comes out empty.")
    ap.add_argument("--ninject", type=int, default=24)
    ap.add_argument("--ref-isa", default="", help="force MF_ISA in the reference")
    ap.add_argument("--isa", default="", help="force MF_ISA in the candidate")
    a = ap.parse_args()

    base = dict(n=a.n, ntmpl=a.templates, ntaps=a.taps, series=a.series,
                band=a.band, threshold=a.threshold, reps=a.reps,
                inject=a.inject, ninject=a.ninject)
    cfgs = {"reference": dict(base, isa=a.ref_isa),
            "candidate": dict(base, isa=a.isa)}
    pys = {"reference": a.reference, "candidate": a.candidate}

    first, times = {}, {"reference": [], "candidate": []}
    order = ["reference", "candidate"]
    for r in range(a.rounds):
        for who in (order if r % 2 == 0 else order[::-1]):
            res = run(pys[who], cfgs[who])
            times[who].append(res["ms"])
            first.setdefault(who, res)

    ref, cand = first["reference"], first["candidate"]
    same = (ref["idx_sum"] == cand["idx_sum"]
            and ref["n_peaks"] == cand["n_peaks"]
            and abs(ref["mag_sum"] - cand["mag_sum"])
                <= 1e-6 * max(1.0, abs(ref["mag_sum"])))

    print("hierarchical, ratio-filter shaped: n=%d, %d templates, %d blocks, "
          "band=%d, threshold=%.1f" % (a.n, a.templates, ref["blocks"],
                                       a.band, a.threshold))
    print("%d interleaved rounds, best of %d within each\n" % (a.rounds, a.reps))
    print("  %-11s %-12s %10s %10s %10s" % ("", "back end", "median", "min", "max"))
    for who in order:
        v = times[who]
        print("  %-11s %-12s %8.2fms %8.2fms %8.2fms"
              % (who, first[who]["backend"], statistics.median(v), min(v), max(v)))
    rm, cm = statistics.median(times["reference"]), statistics.median(times["candidate"])
    print("\n  candidate / reference: %.3fx  (%s)"
          % (cm / rm, "faster" if cm < rm else "slower"))
    print("  output: %s   (%d bins reported, peak magnitude %.6g)"
          % ("IDENTICAL" if same else "*** DIFFERS ***",
             ref["n_peaks"], ref["mag_max"]))
    if a.inject and ref["n_peaks"] == 0:
        print("  *** the correctness pass found nothing, so IDENTICAL means "
              "only that both builds agree the answer is empty")
        return 2
    if not same:
        print("     reference  n=%d idx_sum=%d mag_sum=%.6f"
              % (ref["n_peaks"], ref["idx_sum"], ref["mag_sum"]))
        print("     candidate  n=%d idx_sum=%d mag_sum=%.6f"
              % (cand["n_peaks"], cand["idx_sum"], cand["mag_sum"]))
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
