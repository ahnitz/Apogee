#!/usr/bin/env python3
"""Measure filter dismissal and relative runtime costs using actual kernels.

Accuracy is computed by matchedfilter.gatemodel from the whole reference
profile. This tool independently checks that prediction using injections,
and measures costs that depend on the machine and workload.

    python tools/hmf_tune.py --n 4096 --snr 5 --fd .001 --trials 100000
    python tools/hmf_tune.py --retune-cost --out mycost.txt
"""
import argparse
import gc
import os
import sys
import time

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "tests"))
from test_api import (inspiral_power, template_with_power, noise)  # noqa: E402
import matchedfilter as mf                                    # noqa: E402
sys.path.insert(0, os.path.join(_ROOT, "tools"))


#: Trials per call when measuring on a GPU. The CPU's 64 is a throughput
#: batch for a CPU and a rounding error for a GPU: at 64 pairs the call is
#: almost entirely submit-and-wait, so the sweep would measure launch
#: latency several thousand times over. Accuracy does not care how the
#: trials are grouped -- only how many there are -- so the batch is free to
#: follow the device.
_GPU_BATCH = 2048


def device_batch(device, default=64):
    """Trials per call, sized for whoever is running them."""
    return default if device in (None, "cpu") else _GPU_BATCH


def measure(n, band, U, K, snr, trials, seed=13, batch=None, power=None,
            device=None, thr=None, fd=1e-3):
    """Measured (dismissal, seconds-per-pair) for one configuration.

    Both numbers come from the real filter.  Injections go into a batch of
    data spectra at once, which is how a caller drives it, so the time is
    throughput rather than per-call overhead, and the trial count needed to
    resolve 1e-4 stays affordable.

    `device` picks which implementation is being characterised. CPU and
    GPU use the same algorithm with different arithmetic precision.
    The flat filter stays on the same device as
    the hierarchical one: a dismissal is defined against what the flat
    filter found, and comparing across devices would fold their float
    differences into the answer.
    """
    if batch is None:
        batch = device_batch(device)
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
    flat = mf.MatchedFilter(n, ndata=batch, ntemplates=1, device=device)
    hf = mf.HierarchicalFilter(n, ndata=batch, ntemplates=1, snr=snr, fd=fd,
                               band=band, taps=K, device=device)
    hf.set_reference(power)
    if thr is not None:
        hf.set_coarse_threshold(float(thr))
    flat.set_templates(H[None, :])
    hf.set_templates(H[None, :])

    detected = omitted = 0
    sec = 0.0
    npair = 0
    # exp(2 pi i k L / n) by table lookup rather than ph ** L. The phase
    # ramp only ever takes the n values already in the table, and a complex
    # power recomputes one from scratch per element: measured at 30.7 ms a
    # batch against 0.98 ms, and it was 77% of the whole cell -- the sweep
    # was spending its time building injections, not filtering them. The
    # lookup is also the more accurate of the two, since repeated powers
    # drift and an exact index does not.
    kidx = np.arange(n)
    ph_tab = np.exp(2j * np.pi * kidx / n)
    lag0 = 0
    for _ in range((trials + batch - 1) // batch):
        D = noise((batch, n), rng)
        # One vectorised injection per batch rather than `batch` Python
        # iterations. With the noise pooled this loop WAS the cell: 0.138s
        # of 0.254s at n=1024, against 0.039s of actual filtering. The lag
        # sequence is unchanged -- lag0 advances by 37 per trial and
        # carries across batches -- so the injected data is identical.
        lags = (lag0 + 37 * np.arange(1, batch + 1)) % n
        lag0 = int(lags[-1])
        ramp = ph_tab[(kidx[None, :] * lags[:, None]) % n]
        D += (snr * H[None, :] * ramp).astype(np.complex64)
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
    for o in (flat, hf):
        if getattr(o, "_gpu", None) is not None:
            o._gpu.destroy()
    return (omitted / detected if detected else 1.0), detected, sec / npair


def tune(n, snr, fd, trials=1500, seed=13, bands=None, verbose=True,
         power=None, device=None):
    if bands is None:
        bands = [b for b in (64, 128, 256, 512, 1024, 2048, 4096) if b <= n // 2]
    rows = []
    for band in bands:
        for U in (2,):  # compatibility column; oversampling is no longer selectable
            for K in (4, 8):
                try:
                    dm, det, sec = measure(n, band, U, K, snr, trials, seed,
                                           power=power, device=device, fd=fd)
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


def retune_cost(source, out, trials=4000, jobs=None, verbose=True):
    """Remeasure costs on synthetic references spanning an existing cost file.

    The source provides reference anchors, not accuracy. Interleaved timing
    compares all candidates on each reference, using the current model gate.
    """
    cells = set()
    for line in open(source):
        f = line.split()
        if not f or f[0].startswith('#'):
            continue
        if f[0] == 'COST' and len(f) == 9:
            cells.add((int(f[1]), int(f[2]), float(f[5]), float(f[6]), float(f[7])))
    if not cells:
        raise ValueError('cost file contains no supported cost rows')
    with open(out, 'w') as fh:
        fh.write('# Relative CPU COST rows; current model gate at fd=.001; interleaved timing\n')
        fh.write('# cpu ' + _cpu_name() + '\n')
        fh.write('# COST n band U K snr f beff relative_cost\n')
        for n, anchor, snr, f, be in sorted(cells):
            bands = [1 << k for k in range(6, n.bit_length()-1)]
            configs = [(b, 2, k) for b in bands for k in (4, 8)]
            power = make_ref(n, anchor, f, be)
            ratios, _ = cost_sweep_one_reference(n, power, snr, configs)
            for (band, u, k), ratio in sorted(ratios.items()):
                ff, bb = _feat(power, band)
                fh.write('COST %d %d %d %d %.2f %.6f %.3f %.6f\n' %
                         (n, band, u, k, snr, ff, bb, ratio))
            if verbose:
                print('cost n=%d snr=%.2f f=%.4f beff=%.2f' %
                      (n, snr, f, be), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--snr", type=float, default=5.0)
    ap.add_argument("--fd", type=float, default=1e-3)
    ap.add_argument("--trials", type=int, default=1500)
    ap.add_argument("--retune-cost", nargs="?", const="", metavar="COST",
                    help="re-measure the cost table for this machine, using "
                         "the supplied or shipped cost file's references; writes --out")
    ap.add_argument("--out", default="cost.txt")
    ap.add_argument("--device", default=None, metavar="DEV",
                    help="device to measure ('cpu', 'gpu', 'gpu:1', ...)")
    a = ap.parse_args()
    if a.device and a.device != "cpu":
        import matchedfilter as _mf
        ok = [d for d in _mf.devices() if d.kind == "gpu"]
        if not ok:
            ap.error("no GPU found, so there is nothing to characterise")
        if a.n not in getattr(_mf, "_GPU_SIZES", {a.n}):
            ap.error("the GPU backend does not run n=%d, so it has no "
                     "accuracy to measure there; the shipped table still "
                     "covers it for the CPU" % a.n)
    if a.retune_cost is not None:
        acc = a.retune_cost or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "python", "matchedfilter", "cost.txt")
        retune_cost(acc, a.out, trials=max(a.trials, 2000))
        return
    print("n=%d snr=%.1f fd=%.0e on %s -- every row is the real filter, "
          "not a model\n" % (a.n, a.snr, a.fd, a.device or "cpu"))
    best, _ = tune(a.n, a.snr, a.fd, trials=a.trials, device=a.device)
    print("\nPICK: %s" % (best if best else "nothing met the target"))




def beff_of(p, m):
    """Effective bandwidth of the in-band power, in bins (participation ratio)."""
    q = np.asarray(p[:m], float)
    s = q.sum()
    if s <= 0:
        return 1.0
    q = q / s
    return float(1.0 / np.sum(q ** 2))


def bank_with_power(n, power, nt, seed=5):
    """`nt` DISTINCT unit-norm templates sharing one power spectrum.

    template_with_power has zero phase, so nt copies of it are one template
    repeated -- every pair in the batch then does identical work, which is
    not a bank. Random phase per template keeps the power profile the
    reference describes while making the correlations independent, which is
    what a real bank looks like to the coarse pass.
    """
    rng = np.random.default_rng(seed)
    amp = np.sqrt(np.asarray(power, float))
    h = (amp * np.exp(2j * np.pi * rng.random((nt, n)))).astype(np.complex64)
    return h / np.sqrt((np.abs(h) ** 2).sum(axis=1, keepdims=True))


def bands_for(n, count=6):
    """Candidate first-stage bands at transform length `n`.

    A LADDER IN THE DECIMATION RATIO, n/band, not in absolute band size.

    Two reasons, and the second is the one that bit. First, `n` sets the
    duration of the block, not its frequency content: at a fixed sample rate a
    band of `m` bins is a different FREQUENCY at every `n`, while `n/R` is the
    same fraction of Nyquist at all of them. A caller choosing `n` for how much
    data to analyse at once should not be changing which part of the spectrum
    the first pass keeps.

    Second, the grid this replaces took the six SMALLEST bands at or below
    n/4. At n=262144 that made 8192 the widest first pass considered -- ratio
    32 -- which loses so much signal that the coarse pass escalated 100% of
    pairs at every threshold and the hierarchical filter measured SLOWER than
    the flat one (0.84x at n=65536 snr 5.0). The n/4 cap also excluded band
    2048 at n=4096, which is the best configuration there.

    Ratios 2 to 64 at every length, floored at 256 bins.
    """
    return sorted([n >> k for k in range(1, count + 1) if (n >> k) >= 256],
                  reverse=True)


def make_ref(n, m, f, beff, tol=0.02):
    """Synthetic exponential profile with specified fraction and bandwidth.

    A cost-grid fixture, not an accuracy proxy: matching these two features
    does not fix scalloping. Accuracy checks also use real reference shapes.
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


def measure_cost(n, band, U, K, snr, power, nt=1, nd=64, reps=5,
                 pairs_target=20000, seed=7, fd=1e-3):
    """Median us/pair for one configuration and batch shape.

    Three things matter here and none of them did in the first version.

    Batch shape is a cost column and not an accuracy one: D x T batching
    changes throughput and cannot change a single reported peak, which
    tests/test_api.py pins. So it belongs here and would be noise in the
    accuracy table.

    This docstring used to claim "up to 1.94x". Do not reinstate that number
    without re-measuring: pairs_target below holds TOTAL PAIRS fixed, so a
    1x1 shape runs 200 tiny calls and a 64x64 shape runs 5 large ones, and
    most of what separated them was per-call overhead rather than throughput.
    A clean comparison has to hold work per call fixed, not pairs.

    Noise is redrawn for every batch, so the trigger rate -- which is most of
    the cost, and is set by the coarse threshold and the reference -- is averaged rather
    than sampled once.

    The time is a median over `reps`, not a mean or a minimum. A mean lets one
    descheduled run dominate; a minimum reports an idle machine, which is the
    wrong target when the deployment condition is every core busy.
    """
    rng = np.random.default_rng(seed)
    power = np.ascontiguousarray(power, dtype=np.float32)
    H = np.stack([template_with_power(n, power) for _ in range(nt)])
    hf = mf.HierarchicalFilter(n, ndata=nd, ntemplates=nt, snr=snr, fd=fd,
                               band=band, taps=K)
    hf.set_reference(power)
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


#: Configuration every inner loop includes, so ratios from different
#: references share a scale.  It must be re-measured in each loop rather than
#: once and reused, or its own drift comes back as a common-mode term.
COST_PIVOT = (1024, 2, 8)


def cost_sweep_one_reference(n, power, snr, configs, reps=4, batch=64,
                             nt=16, pairs=6000, seed=11, group=None,
                             mem_budget=4e8):
    """Time every configuration on ONE reference, and return relative costs.

    This is the whole point of the restructure.  Timing each configuration
    against a reference built to match its own key -- which is what the first
    version did -- means band 512 and band 1024 are measured on different
    signals and ranked against each other anyway.  That is not a noisy
    comparison, it is not a comparison.

    Configurations are swept in GROUPS, with the pivot in every one, rather
    than all at once.  A plan holds (batch + ntemplates) * n complex64 buffers
    -- 50 MB at n=262144 -- and holding all 48 alive came to 2.4 GB a worker,
    77 GB across 32, which is what killed the first regeneration run.

    Grouping is NOT free, so the group is sized to a memory budget rather than
    fixed: the pivot is re-measured per group, and between-group drift then
    enters the ratio, which took the ratio CV from 0.82% to 2.48% when every
    length was forced into groups of six.  A plan at n=4096 is 2 MB, so all 48
    fit inside the budget and the precision is untouched; only the largest
    lengths, where a plan is 50 MB, pay anything.
    """
    rng = np.random.default_rng(seed)
    # A real BANK, not one template counted nt times.
    #
    # The plans were built with ntemplates=1 and the time then divided by nt
    # as though a batch had been filtered. That measured the UNBATCHED regime
    # and labelled it batched, and it is the largest known error in
    # selection: with a single template there is nothing for the coarse pass
    # to amortise against, so K=4's cheaper interpolation never shows its
    # advantage and the table ranked K=8 ahead of it where measurement has
    # K=4 10.6% faster.
    H = bank_with_power(n, power, nt, seed=seed)
    per = int(np.clip(pairs // (nt * batch), 2, 60))
    data = [noise((batch, n), rng) for _ in range(per)]

    cfgs = list(configs)
    if group is None:
        # (data + template) split buffers, re and im, plus the hierarchical
        # band state; rounded up generously rather than modelled exactly.
        per_plan = 3.0 * (batch + nt) * n * 4 * 2
        group = int(max(4, min(len(cfgs), mem_budget // max(per_plan, 1))))
    pivot = COST_PIVOT if COST_PIVOT in cfgs else cfgs[0]
    others = [c for c in cfgs if c != pivot]
    med, pivot_runs = {}, []
    for i in range(0, max(len(others), 1), max(group - 1, 1)):
        chunk = [pivot] + others[i:i + max(group - 1, 1)]
        plans = {}
        skipped = []
        for cfg in chunk:
            band, U, K = cfg
            hf = mf.HierarchicalFilter(n, ndata=batch, ntemplates=nt, snr=snr,
                                       fd=1e-3, band=band, taps=K)
            hf.set_reference(power)
            hf.set_templates(H)
            # A configuration the library declines -- band 64 has no
            # calibrated coarse threshold at any n -- must not kill the
            # sweep. Before this, --retune-cost died on the first such cell
            # and produced only n=1024, which is to say the cost table could
            # not be regenerated at all. The refusal surfaces on first run,
            # not at construction, so it is provoked here.
            try:
                hf.set_data(data[0])
                hf.run(binsize=n, threshold=snr, raw=True)
            except ValueError as e:
                skipped.append((cfg, str(e).split(":")[0]))
                continue
            plans[cfg] = hf
        if skipped:
            print("    skipped %d configuration(s) the library declines: %s"
                  % (len(skipped), ", ".join("band %d/K%d (%s)"
                                             % (c[0], c[2], why)
                                             for c, why in skipped)))
        if pivot not in plans:
            continue                          # nothing to normalise against
        acc = {c: [] for c in plans}
        for _ in range(reps):
            for cfg in plans:                 # cycle, do not run to completion
                hf = plans[cfg]
                t0 = time.perf_counter()
                for d in data:
                    hf.set_data(d)
                    hf.run(binsize=n, threshold=snr, raw=True)
                acc[cfg].append((time.perf_counter() - t0) / (per * nt * batch))
        piv = float(np.median(acc[pivot]))
        pivot_runs += acc[pivot]
        for c in plans:
            if c == pivot and pivot in med:
                continue
            med[c] = float(np.median(acc[c])) / max(piv, 1e-30)
        plans.clear()                         # free before the next group
        gc.collect()
        if not others:
            break
    # Standard error of the estimate, NOT max/min. A range grows with the
    # sample count by construction -- measured, it went 3.7% to 7.5% purely by
    # adding repeats -- so reporting one as "what the ratios are worth" claims
    # a precision that is not being measured and gets worse the harder you
    # look.
    pv = np.asarray(pivot_runs, float)
    resid = float(np.std(pv) / max(np.mean(pv), 1e-30) / np.sqrt(len(pv)))
    return med, resid


def cost_over_realisations(n, power, snr, configs, draws=8, reps=3, **kw):
    """Average the cost ratios over independent NOISE REALISATIONS.

    Repeating the clock on one realisation does not help: measured, the ratio
    CV was 2.5%, 1.8%, 2.8% at 3, 8 and 20 repeats -- flat, because the
    variation is not in the timer. It is in the data. A different noise draw
    escalates differently, so it genuinely costs something different, and that
    is what has to be averaged.

    Averaging draws behaves exactly as independent samples should:

        draws     1      2      4      8
        CV     3.33%  2.27%  1.56%  0.82%
        1/sqrt 3.33%  2.35%  1.66%  1.18%

    Eight draws puts the ratio CV below 1%, under the 3.5% differences that
    selection was previously unable to resolve.
    """
    acc, res = {}, []
    for k in range(draws):
        rel, r = cost_sweep_one_reference(n, power, snr, configs, reps=reps,
                                          seed=101 + 7 * k, **kw)
        res.append(r)
        for c, v in rel.items():
            acc.setdefault(c, []).append(v)
    out = {c: float(np.mean(v)) for c, v in acc.items()}
    # spread of the per-draw ratios, divided by sqrt(draws): the precision the
    # averaged number actually carries
    cv = float(np.median([np.std(v) / max(np.mean(v), 1e-30) / np.sqrt(len(v))
                          for v in acc.values()]))
    return out, cv


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


if __name__ == "__main__":
    main()
