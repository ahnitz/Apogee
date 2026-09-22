#!/usr/bin/env python3
"""Tune the whole first-stage configuration by running the real filter.

Not a model.  An earlier version of this re-derived the statistic in numpy and
Monte-Carloed that, and it was wrong in the way re-derivations are wrong: it
reported a measured false dismissal of 0.0 for band 256 at U=1 -- a
configuration the captures show triggering 60% of the time, and which misses
244 of 842 triggers.  Anything that does not run the code cannot be trusted to
tune the code.

So every candidate here is built as an actual HierarchicalFilter with that
(band, oversample, taps), handed the same reference and bank, and run against
injections.  The ungated MatchedFilter on the same data is the truth, exactly
as tools/hier_bench.py does it, and a dismissal is a peak the flat filter
reports that the hierarchical one does not.  Cost is wall time of the same
call, not a formula.

The consequence worth having: after any change to the kernel or the gate, this
can be re-run and will say whether the compiled choices still hold.

What decides the answer is how the SNR accumulates with frequency, which is
exactly what the reference states -- so the tuner is parameterised by it.  A
template whose own power equals the reference reproduces that accumulation,
and therefore stands in for any bank sharing the profile, including a ratio
filter whose own spectrum looks nothing like its output.  The filter's shape
does not need reconstructing; the rest is how that accumulation interacts with
noise, which is what the simulation is for.

Given the captures' own reference (0.9335 of the SNR below band 512, 0.9875
below 1024) it reproduces reality: band 512 dismisses 1.97e-3 and band 1024
2.81e-3 against a 1e-3 target, both rejected, and band 2048 dismisses none.
2048 is what the compiled table picks and the only one of the three returning
all 893 triggers through pycbc.

Run instead against `inspiral_power`, whose accumulation is 0.9999 below bin
512, it picks band 512 at U=1 -- correctly for that profile, and uselessly,
since nothing real has it.  The profile is the input that matters, and getting
it wrong is how a tuner validates itself and still ships a configuration that
loses 244 of 842 triggers.

THE SYNTHETIC REFERENCE FAMILY DOES NOT REPRODUCE THE REAL ONE, and until it
does no table generated from it is safe.  A 240-cell parallel sweep at 20000
trials a cell (tools/sweep-n4096-fd1e-3.json) says band 512 at U=2, K=8
dismisses 5.5e-4 to 6.7e-4 for synthetic references with 0.90 to 0.95 of their
power below the edge -- comfortably inside a 1e-3 target.  The captures' real
reference sits at 0.9335, squarely in that range, and measures 1.97e-3: it
fails where the synthetic passes.  The two agree on f(512) to four figures and
disagree on g (0.9979 against 1.0000) and so on the gate (4.237 against
4.266), and the Rayleigh tail is steep enough there that 0.7% of gate
straddles the target.

Nor does it collapse onto f_eff = f*g^2, the one scalar the runtime already
measures exactly.  At band 512, U=2, K=8 the synthetic family dismisses
5.3e-4, 6.8e-4, 1.2e-3 and 8.0e-4 at concentrations 0.88, 0.92, 0.95 and 0.97
-- not even monotonic -- while the captures' real reference dismisses 3.4e-3,
three to six times worse than any of them.  The real curve is harder than
anything this family produces, so no single number drawn from it can order the
candidates.  That is what it means for the power-versus-frequency curve to be
the input: different problems have genuinely different curves, and the
accumulated power at each candidate edge is the characterisation, not a scalar
summary of it.

WHAT THE TABLE SHOULD BE KEYED ON.  The bands do not need a joint model of
the whole curve -- each can be trained on its own -- but the features for band
m are the accumulated powers at m AND at every candidate edge below it, not at
m alone.  At band 512 the captures and a synthetic can agree on f(512) and
still differ threefold in dismissal, because they put 85.2% and 94.7% of their
IN-BAND power below 256 respectively, and that is what sets the correlation
peak width, hence the scalloping, hence g.  So:

    band m -> keyed on f(m), the accumulated power at the edge,
              and B_eff(m), the EFFECTIVE BANDWIDTH of the power inside it.

B_eff is the participation ratio of the in-band power, (sum p)^2 / sum p^2, in
bins.  It is the physical parameter: it sets the correlation peak width, and
the scalloping is the lag spacing measured against that width.  The extremes
make it obvious -- all the power in one bin is B_eff = 1, a maximally wide
peak the coarse grid resolves perfectly; power flat across the band is
B_eff = m and a peak one sample wide, which the grid misses.

That is two numbers per band, not a functional on curves, and both are stated
directly by the caller's reference.

It also measures how far off the synthetic family is.  At band 512 every
make_template reference lands at B_eff 6.8 to 18.8 bins while the captures'
real reference is at 190.2 -- ten to twenty-seven times broader, a different
regime, and exactly the direction that explains its 3.4e-3 dismissal against
their 5.3e-4 to 1.2e-3.  A training family has to span B_eff from about 1 to
m; this one spans a twentieth of that at the top end and none of it at the
bottom.

VALIDATED.  Holding f(512) at the captures' 0.9335 and varying only the
in-band profile -- exponential with the decay constant sweeping B_eff --
dismissal rises with B_eff as the mechanism says it must:

    B_eff      10     40    160    190*    343    452
    dismiss  4.8e-4 1.7e-4 9.1e-4 1.5e-3 2.7e-3 3.8e-3     * the real reference

Interpolating the synthetic points to B_eff = 190 predicts ~1.2e-3 where the
real reference measures 1.5e-3, agreement to ~25% at these trial counts.  So
the real curve is not special: it sits on the surface, and the earlier
mismatch was entirely that make_template could not reach its bandwidth.  A
family of exponential in-band profiles spans the axis and can carry the
training.  At run
time each candidate is evaluated at its own features and the cheapest
admissible one wins.

So the grid has to be built from references that reproduce real ones -- either
captured references directly, or a family validated against them -- not from
make_template.  Generating from make_template would hardcode a table that
passes its own validation and loses triggers on real data, which is the same
failure this tool exists to prevent.

Still short of a shippable table, for two further reasons.  6000 trials resolve ~3e-4,
enough for a 1e-3 target but not the 1e-4 one.  And a single scalar `want_f`
does not determine the answer: a synthetic profile with 0.95 of its SNR below
the band edge picks band 256, where the captures' real reference -- 0.9335
below the same edge -- needs 2048.  Two references agreeing on one cumulative
point do not agree on the statistic, so the table's key has to carry more of
the accumulation curve than one number, or be built from real references.

    python tools/hmf_tune.py --n 4096 --snr 5.0 --fd 1e-3 --trials 4000
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, "tests")
from test_api import (inspiral_power, template_with_power, noise)  # noqa: E402
import matchedfilter as mf                                    # noqa: E402
sys.path.insert(0, "tools")
import hmf_design as D_design                                 # noqa: E402


def measure(n, band, U, K, snr, trials, seed=13, batch=64, power=None,
            gate=1.0):
    """Measured (dismissal, seconds-per-pair) for one configuration.

    Both numbers come from the real filter.  Injections go into a batch of
    data spectra at once, which is how a caller drives it, so the time is
    throughput rather than per-call overhead, and the trial count needed to
    resolve 1e-4 stays affordable.
    """
    rng = np.random.default_rng(seed)
    if power is None:
        power = inspiral_power(n)
    power = np.ascontiguousarray(power, dtype=np.float32)
    # The statistic's distribution is fixed by how the SNR accumulates with
    # frequency, which is what the reference states.  A template whose own
    # power equals the reference reproduces that accumulation exactly, so it
    # stands in for any bank with the same profile -- including a ratio filter
    # whose own spectrum looks nothing like its output.
    H = template_with_power(n, power)
    flat = mf.MatchedFilter(n, ndata=batch, ntemplates=1)
    hf = mf.HierarchicalFilter(n, ndata=batch, ntemplates=1, snr=snr, fd=1e-3,
                               band=band, oversample=U, taps=K)
    hf.set_reference(power)
    if gate != 1.0:
        hf._ensure().set_gate_margin(float(gate))
    flat.set_templates(H[None, :])
    hf.set_templates(H[None, :])

    detected = omitted = 0
    sec = 0.0
    npair = 0
    ph = np.exp(2j * np.pi * np.arange(n) / n)
    lag0 = 0
    for _ in range((trials + batch - 1) // batch):
        D = noise((batch, n), rng)
        for j in range(batch):
            lag0 = (lag0 + 37) % n
            D[j] += (snr * H * ph ** lag0).astype(np.complex64)
        flat.set_data(D)
        hf.set_data(D)
        a_ = flat.run(binsize=n, threshold=snr, raw=True)
        t0 = time.perf_counter()
        b_ = hf.run(binsize=n, threshold=snr, raw=True)
        sec += time.perf_counter() - t0
        npair += batch
        ai = np.array(a_[0])[:, 0, 0]
        bi = np.array(b_[0])[:, 0, 0]
        hit = ai >= 0
        detected += int(hit.sum())
        omitted += int((bi[hit] < 0).sum())
    return (omitted / detected if detected else 1.0), detected, sec / npair


def tune(n, snr, fd, trials=1500, seed=13, bands=None, verbose=True,
         power=None):
    if bands is None:
        bands = [b for b in (256, 512, 1024, 2048, 4096) if b <= n // 2]
    rows = []
    for band in bands:
        for U in (1, 2):
            for K in (4, 8):
                try:
                    dm, det, sec = measure(n, band, U, K, snr, trials, seed,
                                           power=power)
                except Exception as e:                       # unsupported combo
                    if verbose:
                        print("  band %-5d U=%d K=%-3d  unavailable (%s)"
                              % (band, U, K, e))
                    continue
                ok = dm <= fd
                rows.append(dict(band=band, U=U, K=K, dismissal=dm,
                                 detected=det, sec=sec, ok=ok))
                if verbose:
                    print("  band %-5d U=%d K=%-3d  dismissed %.3e of %-6d "
                          "%8.3f us/pair  %s" % (band, U, K, dm, det, sec * 1e6,
                                            "OK" if ok else "REJECT"))
    live = [r for r in rows if r["ok"]]
    return (min(live, key=lambda r: r["sec"]) if live else None), rows


def _cpu_name():
    try:
        for l in open("/proc/cpuinfo"):
            if l.startswith("model name"):
                return l.split(":", 1)[1].strip()
    except Exception:
        pass
    return "unknown"


def retune_cost(accuracy, out, trials=4000, jobs=None, verbose=True):
    """Re-measure only the COST rows, keeping the FDR rows as they are.

    This is the half that is about your machine.  The FDR rows describe the
    statistic and travel; the COST rows are wall time on one CPU with one
    build, so they are the ones worth regenerating locally.
    """
    import multiprocessing as mp
    fdr = [l.rstrip("\n") for l in open(accuracy)
           if l.startswith(("ACC", "FDR"))]
    jobs = jobs or max(1, (os.cpu_count() or 2) - 2)
    work, seen = [], set()
    for ln in fdr:
        f = ln.split()
        key = (int(f[1]), int(f[2]), int(f[3]), int(f[4]), float(f[5]),
               float(f[6]), float(f[7]))
        if key in seen:
            continue
        seen.add(key)
        work.append((key[0], key[1], key[2], key[3], key[4], key[5], key[6], trials))
    if verbose:
        print("re-measuring %d cost cells on %d cores" % (len(work), jobs), flush=True)
    with mp.Pool(jobs) as pool:
        rows = list(pool.imap_unordered(_cost_cell, work, chunksize=1))
    with open(out, "w") as fh:
        fh.write("# matchedfilter COST table -- microseconds per pair, measured\n")
        fh.write("# cpu     %s\n" % _cpu_name())
        fh.write("# trials  %d pure-noise per cell at the search threshold\n#\n"
                 % trials)
        fh.write("# n band U K snr f beff us_per_pair\n")
        for r in sorted(rows, key=lambda x: (x["band"], x["K"], x["snr"], x["f"])):
            if "error" in r:
                continue
            fh.write("COST %d %d %d %d %.2f %.4f %.1f %.4f\n"
                     % (r["n"], r["band"], r["U"], r["K"], r["snr"], r["f"],
                        r["beff_act"], r["sec"] * 1e6))
    if verbose:
        print("wrote %s" % out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--snr", type=float, default=5.0)
    ap.add_argument("--fd", type=float, default=1e-3)
    ap.add_argument("--trials", type=int, default=1500)
    ap.add_argument("--retune-cost", nargs="?", const="", metavar="ACCURACY",
                    help="re-measure the cost table for this machine, using "
                         "the shipped accuracy table's cells; writes --out")
    ap.add_argument("--out", default="cost.txt")
    a = ap.parse_args()
    if a.retune_cost is not None:
        acc = a.retune_cost or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "python", "matchedfilter", "accuracy.txt")
        retune_cost(acc, a.out, trials=max(a.trials, 2000))
        return
    print("n=%d snr=%.1f fd=%.0e -- every row is the real filter, not a model\n"
          % (a.n, a.snr, a.fd))
    best, _ = tune(a.n, a.snr, a.fd, trials=a.trials)
    print("\nPICK: %s" % (best if best else "nothing met the target"))


if __name__ == "__main__":
    main()


def profile(n, want_f):
    """A reference whose SNR accumulation puts `want_f` of the power below the
    n/8 band edge -- the same parameterisation hmf_design uses, so the two
    tables are indexed alike."""
    H = D_design.make_template(n, n // 8, want_f)
    return (np.abs(H) ** 2).astype(np.float32)


def grid(ns, want_fs, snrs, fds, trials, verbose=True):
    """Measured best configuration for every cell. Returns a list of rows."""
    out = []
    for n in ns:
        for wf in want_fs:
            ref = profile(n, wf)
            for T in snrs:
                for fd in fds:
                    best, rows = tune(n, T, fd, trials=trials, power=ref,
                                      verbose=False)
                    if verbose:
                        print("  n=%-6d want_f=%.2f snr=%.1f fd=%.0e -> %s"
                              % (n, wf, T, fd,
                                 ("band %d U=%d K=%d  %.3e  %.2f us/pair"
                                  % (best["band"], best["U"], best["K"],
                                     best["dismissal"], best["sec"] * 1e6))
                                 if best else "NOTHING MET THE TARGET"))
                    out.append(dict(n=n, want_f=wf, snr=T, fd=fd, best=best,
                                    rows=rows))
    return out


def emit(rows, path, trials):
    """Write the measured table as a C header the library compiles in."""
    lines = [
        "/* Generated by tools/hmf_tune.py -- do not edit by hand.",
        " *",
        " * Unlike hmf_table.h, every row here was MEASURED by running the real",
        " * filter against injections and counting the peaks the ungated filter",
        " * reports that it does not.  A row exists only if its dismissal came in",
        " * at or under the target; the cheapest survivor wins.  %d trials a" % trials,
        " * candidate, so rates below about %.0e are not resolved." % (3.0 / max(trials, 1)),
        " *",
        " * Keyed on all four axes the answer depends on.  want_f is how much of",
        " * the SNR accumulates below the n/8 band edge, which is what the",
        " * caller's reference states; n matters because the cost per point is",
        " * not scale-free and the lag count grows with it.",
        " */",
        "#ifndef AP_HMF_TUNED_H", "#define AP_HMF_TUNED_H", "#include <stddef.h>", "",
        "typedef struct { unsigned n; float want_f, snr, fd;",
        "                 unsigned band; int u, k; float fd_meas; } hmf_tuned;",
        "static const hmf_tuned hmf_tuned_picks[] = {",
    ]
    kept = 0
    for r in rows:
        b = r["best"]
        if not b:
            continue
        kept += 1
        lines.append("  { %du, %.4ff, %.2ff, %.1ef, %du, %d, %d, %.3ef },"
                     % (r["n"], r["want_f"], r["snr"], r["fd"],
                        b["band"], b["U"], b["K"], b["dismissal"]))
    lines += ["};", "#define HMF_NTUNED %d" % kept, "", "#endif", ""]
    open(path, "w").write("\n".join(lines))
    return kept


def f_min(n, band, U, K, snr, fd, trials=4000, lo=0.50, hi=0.999, tol=0.01):
    """Least accumulated fraction AT THIS BAND for which the configuration
    meets the target.

    A single global number cannot key the table: two references agreeing on
    how much SNR sits below one edge disagree everywhere else, and the
    captures' reference (0.9335 below 512) needs a wider band than a synthetic
    one at 0.95 does.  Judging each candidate on the accumulation at ITS OWN
    edge removes that -- the threshold simply sits between the two.

    Bisects on f, building a reference with that much power below `band`.
    """
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        ref = (np.abs(D_design.make_template(n, band, mid)) ** 2).astype(np.float32)
        dm, det, _ = measure(n, band, U, K, snr, trials, power=ref)
        if det and dm <= fd:
            hi = mid          # this much accumulation is enough
        else:
            lo = mid
    return hi


def _cell(job):
    """One (n, band, U, K, snr, fd, want_f) measurement. Top level for pickling."""
    n, band, U, K, snr, fd, wf, trials = job
    try:
        ref = (np.abs(D_design.make_template(n, band, wf)) ** 2).astype(np.float32)
        dm, det, sec = measure(n, band, U, K, snr, trials, power=ref)
        return dict(n=n, band=band, U=U, K=K, snr=snr, fd=fd, want_f=wf,
                    dismissal=dm, detected=det, sec=sec, ok=(det > 0 and dm <= fd))
    except Exception as e:
        return dict(n=n, band=band, U=U, K=K, snr=snr, fd=fd, want_f=wf,
                    error=str(e), ok=False)


def sweep(ns, bands, Us, Ks, snrs, fds, want_fs, trials, jobs):
    """Run every cell in parallel. Returns the raw rows."""
    import multiprocessing as mp
    work = [(n, b, U, K, T, fd, wf, trials)
            for n in ns for b in bands if b <= n // 2
            for U in Us for K in Ks for T in snrs for fd in fds for wf in want_fs]
    with mp.Pool(jobs) as pool:
        out = []
        for i, r in enumerate(pool.imap_unordered(_cell, work, chunksize=1)):
            out.append(r)
            if (i + 1) % 25 == 0:
                print("  %d/%d" % (i + 1, len(work)), flush=True)
    return out


def beff_of(p, m):
    """Effective bandwidth of the in-band power, in bins (participation ratio)."""
    q = np.asarray(p[:m], float)
    s = q.sum()
    if s <= 0:
        return 1.0
    q = q / s
    return float(1.0 / np.sum(q ** 2))


def make_ref(n, m, f, beff, tol=0.02):
    """A reference with in-band fraction `f` at band m and bandwidth `beff`.

    Exponential in-band, decay solved for the bandwidth; the family the real
    captures were shown to lie on.  B_eff runs 1 (all power in one bin, a
    maximally wide correlation peak) to m (flat, a peak one sample wide), and
    a training set has to span it -- make_template only reaches a twentieth.
    """
    lo, hi = 0.3, float(4 * m)
    k = np.arange(m)
    for _ in range(60):
        tau = 0.5 * (lo + hi)
        b = beff_of(np.exp(-k / tau), m)
        if abs(b - beff) < tol * beff:
            break
        if b < beff:
            lo = tau
        else:
            hi = tau
    p = np.zeros(n)
    p[:m] = np.exp(-k / tau)
    p[:m] *= f / p[:m].sum()
    out = np.arange(m, n // 2)
    if len(out):
        p[m:n // 2] = np.exp(-(out - m) / max(400.0, m / 4.0))
        p[m:n // 2] *= (1.0 - f) / p[m:n // 2].sum()
    return p.astype(np.float32)


def _fdr_cell(job):
    n, m, U, K, snr, f, be, trials, gate = job
    try:
        ref = make_ref(n, m, f, be)
        dm, det, sec = measure(n, m, U, K, snr, trials, power=ref, gate=gate)
        return dict(n=n, band=m, U=U, K=K, snr=snr, f=f, beff=be, gate=gate,
                    beff_act=beff_of(ref, m), dismissal=dm, detected=det, sec=sec)
    except Exception as e:
        return dict(n=n, band=m, U=U, K=K, snr=snr, f=f, beff=be, gate=gate,
                    nt=locals().get("nt"), nd=locals().get("nd"), error=str(e))


def measure_cost(n, band, U, K, snr, power, nt=1, nd=64, reps=5,
                 pairs_target=20000, gate=1.0, seed=7):
    """Median us/pair for one configuration and batch shape.

    Three things matter here and none of them did in the first version.

    Batch shape is a cost column and not an accuracy one: D x T batching
    changes throughput by up to 1.94x and cannot change a single reported
    peak, which tests/test_api.py pins. So it belongs here and would be noise
    in the accuracy table.

    Noise is redrawn for every batch, so the trigger rate -- which is most of
    the cost, and is set by the gate and the reference -- is averaged rather
    than sampled once.

    The time is a median over `reps`, not a mean or a minimum. A mean lets one
    descheduled run dominate; a minimum reports an idle machine, which is the
    wrong target when the deployment condition is every core busy.
    """
    rng = np.random.default_rng(seed)
    power = np.ascontiguousarray(power, dtype=np.float32)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=snr, fd=1e-3,
                               band=band, oversample=U, taps=K)
    hf.set_reference(power)
    if gate != 1.0:
        hf._ensure().set_gate_margin(float(gate))
    hf.set_templates(H)
    # Cap the call count. A 1x1 shape would otherwise need `pairs_target`
    # separate run() calls per repeat -- 40000 of them, each paying full
    # Python call overhead, which is minutes for one cell and measures the
    # binding rather than the kernel. Small shapes are intrinsically slow per
    # pair; that is the thing being measured, and 200 calls shows it.
    per = int(np.clip(pairs_target // max(1, nt * nd), 5, 200))
    times, fired, npair = [], 0, 0
    for _ in range(reps):
        t = 0.0
        for _ in range(per):
            hf.set_data(noise((nd, n), rng))     # fresh realisation each batch
            t0 = time.perf_counter()
            b = hf.run(binsize=n, threshold=snr, raw=True)
            t += time.perf_counter() - t0
            fired += int((np.array(b[0])[:, :, 0] >= 0).sum())
            npair += nt * nd
        times.append(t / (per * nt * nd))
    return float(np.median(times)), fired / max(npair, 1)


def _cost_cell(job):
    n, m, U, K, snr, f, be, gate, nt, nd = job
    try:
        ref = make_ref(n, m, f, be)
        sec, rate = measure_cost(n, m, U, K, snr, ref, nt=nt, nd=nd, gate=gate)
        return dict(n=n, band=m, U=U, K=K, snr=snr, f=f, beff=be, gate=gate,
                    nt=nt, nd=nd, beff_act=beff_of(ref, m), sec=sec, rate=rate)
    except Exception as e:
        return dict(n=n, band=m, U=U, K=K, snr=snr, f=f, beff=be, gate=gate,
                    nt=locals().get("nt"), nd=locals().get("nd"), error=str(e))


def measure_tc(n, band, U, K, snr, power, fd, trials=12000, lo=0.60, hi=1.25,
               tol=0.015):
    """The gate at which measured dismissal reaches `fd`, and the g it implies.

    hmf_tc supplies this from a Rice model. The gate decomposes exactly as
    t_c = T*sqrt(f_eff) - c(f_eff, fd) -- the SNR dependence is analytic and
    only the noise allowance c needs measuring -- so this measures the one
    quantity that is not already arithmetic. Bisects the gate scale, since
    that is the only handle the library exposes on an absolute gate.
    """
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        dm, det, _ = measure(n, band, U, K, snr, trials, power=power, gate=mid)
        if det and dm <= fd:
            lo = mid            # still safe: push the gate up
        else:
            hi = mid
    return lo


def _tc_cell(job):
    n, m, U, K, snr, f, be, fd, trials = job
    try:
        ref = make_ref(n, m, f, be)
        scale = measure_tc(n, m, U, K, snr, ref, fd, trials=trials)
        return dict(n=n, band=m, U=U, K=K, snr=snr, f=f, beff=be, fd=fd,
                    beff_act=beff_of(ref, m), gate_scale=scale)
    except Exception as e:
        return dict(n=n, band=m, U=U, K=K, snr=snr, f=f, beff=be, fd=fd,
                    error=str(e))


#: Configuration every inner loop includes, so ratios from different
#: references share a scale.  It must be re-measured in each loop rather than
#: once and reused, or its own drift comes back as a common-mode term.
COST_PIVOT = (1024, 2, 8, 1.00)


def cost_sweep_one_reference(n, power, snr, configs, reps=4, batch=64,
                             nt=16, pairs=6000, seed=11):
    """Time every configuration on ONE reference, and return relative costs.

    This is the whole point of the restructure.  Timing each configuration
    against a reference built to match its own key -- which is what the first
    version did -- means band 512 and band 1024 are measured on different
    signals and ranked against each other anyway.  That is not a noisy
    comparison, it is not a comparison.

    Holding the reference fixed makes the inner loop mutually comparable by
    construction, and dividing by a pivot measured in the same loop cancels
    everything common: clock and turbo state, contention, cache temperature,
    allocator luck, the machine itself.  Only the configuration's relative
    cost survives, which is the only thing selection needs -- it never
    compares across references.

    Configurations are cycled `reps` times rather than each run to completion,
    so slow drift spreads over all of them instead of landing on whichever
    went last.  The pivot's own spread across those passes is reported: it is
    the residual noise after cancellation, and says what the ratios are worth.
    """
    rng = np.random.default_rng(seed)
    power = np.ascontiguousarray(power, dtype=np.float32)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    plans = {}
    for cfg in configs:
        band, U, K, gate = cfg
        hf = mf.HierarchicalFilter(n, ndata=batch, ntemplates=nt, snr=snr,
                                   fd=1e-3, band=band, oversample=U, taps=K)
        hf.set_reference(power)
        if gate != 1.0:
            hf._ensure().set_gate_margin(float(gate))
        hf.set_templates(H)
        plans[cfg] = hf
    per = int(np.clip(pairs // (nt * batch), 2, 60))
    acc = {c: [] for c in configs}
    data = [noise((batch, n), rng) for _ in range(per)]
    for _ in range(reps):
        for cfg in configs:                      # cycle, do not run to completion
            hf = plans[cfg]
            t0 = time.perf_counter()
            for d in data:
                hf.set_data(d)
                hf.run(binsize=n, threshold=snr, raw=True)
            acc[cfg].append((time.perf_counter() - t0) / (per * nt * batch))
    med = {c: float(np.median(v)) for c, v in acc.items()}
    piv = med.get(COST_PIVOT)
    if not piv:
        piv = min(med.values())
    pv = acc.get(COST_PIVOT) or list(acc.values())[0]
    resid = float(max(pv) / min(pv) - 1.0)       # what the ratios are worth
    return {c: v / piv for c, v in med.items()}, resid


def cost_grid(n, snr_list, bands, Ks, gates, f_list, be_fracs, reps=4,
              nt=16, batch=64, verbose=True):
    """Relative cost per configuration, averaged over many references.

    Reference outer, configurations inner: each sweep is internally comparable
    and contributes ratios, so sweeps taken under different machine conditions
    pool without normalising between them.  The features recorded against a row
    are the reference's OWN f and B_eff at that band -- what the library
    computes at selection time -- not the parameters the reference was built
    from, which is the mistake the first table made.
    """
    configs = [(b, 2, K, g) for b in bands for K in Ks for g in gates]
    if COST_PIVOT not in configs:
        configs.append(COST_PIVOT)
    rows, resids = [], []
    for snr in snr_list:
        for f in f_list:
            for bf in be_fracs:
                for anchor in bands:          # build the reference around each band
                    power = make_ref(n, anchor, f, max(2.0, bf * anchor))
                    rel, resid = cost_sweep_one_reference(
                        n, power, snr, configs, reps=reps, nt=nt, batch=batch)
                    resids.append(resid)
                    for cfg, r in rel.items():
                        band, U, K, gate = cfg
                        ff, bb = _feat(power, band)
                        rows.append(dict(n=n, band=band, U=U, K=K, snr=snr,
                                         f=ff, beff=bb, gate=gate, rel=r))
                    if verbose:
                        print("  snr %.1f f %.2f be %.2f anchor %d: resid %.1f%%"
                              % (snr, f, bf, anchor, 100 * resid), flush=True)
    return rows, resids


def _feat(power, m):
    p = np.asarray(power, float)
    p = np.where(p > 0, p, 0.0)
    tot = p.sum()
    inb = p[:m]
    s = inb.sum()
    if tot <= 0 or s <= 0:
        return 0.0, 1.0
    q = inb / s
    return float(s / tot), float(1.0 / np.sum(q ** 2))
