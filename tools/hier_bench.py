#!/usr/bin/env python3
"""The iteration harness for the hierarchical filter.

Shaped like the search it exists for: a long reference-SNR series cut into
overlap-save blocks, filtered against a correlated bank, at a threshold low
enough that the second stage actually runs.  Pure noise at snr 6 triggers on
nothing, and a change that is measured there is measured on the coarse pass
alone.

It reports three things together, because none of them means much alone:

  timing    ms per segment, against the flat filter on the same blocks
  proof     two checks.  Against the flat filter: the same peaks, at the same
            lags.  Magnitudes are compared to fp32 tolerance rather than bit
            for bit, because this drives the flat filter from a spectrum
            numpy computed in float64 while run_series computes its own in
            float32; the filter is the same, the input differs in the last
            bit.  Then internally: lowering the first stage must report a
            superset, bit for bit where both report.  An omission fails the
            one-sided guarantee and is the thing to watch.
  profile   where the time went, with MF_HMF_PROF

    python tools/hier_bench.py --fixture hier-00.npz     # a real captured call
    python tools/hier_bench.py                          # synthetic, snr 5.0
    python tools/hier_bench.py --quick                  # smaller, fast loop

A fixture is the better test by a wide margin: it is the exact input
pycbc_inspiral_fir handed the library, together with the output it got back,
so nothing about the data, the bank or the normalisation has to be guessed --
and every one of those guesses has been wrong here at least once.  Capture one
with MF_CAPTURE=<dir> on a pycbc_inspiral_fir run using
--ratio-filter-engine matchedfilter-hierarchical.
"""
import argparse
import os
import sys
import time

import numpy as np


def bank(n, ntmpl, rng, clusters=8, overlap=0.95):
    """A bank of overlapping clusters.

    Independent random phases make every template orthogonal to every other,
    so exactly one fires per signal and the second stage never sees a batch.
    A chirp-phase grid went the other way here: it was degenerate enough that
    one injection lit up half the bank.  Neither is a search.

    So build the structure directly.  Each cluster has a seed, and its members
    are the seed plus a controlled amount of fresh randomness, giving a known
    overlap with the seed and roughly overlap**2 with each other.  A signal
    then fires its own cluster and leaves the rest alone.
    """
    k = np.arange(n)
    power = np.zeros(n, np.float32)
    power[1:n // 2] = (k[1:n // 2] ** (-7.0 / 3.0)).astype(np.float32)
    power /= power.sum()
    amp = np.sqrt(power)

    def rand_spec(m):
        z = amp * np.exp(1j * rng.uniform(0, 2 * np.pi, (m, n)))
        z[:, n // 2:] = 0
        return z

    eps = np.sqrt(1.0 / overlap ** 2 - 1.0)
    seeds = rand_spec(clusters)
    h = seeds[np.arange(ntmpl) % clusters] + eps * rand_spec(ntmpl)
    h = h.astype(np.complex64)
    h /= np.sqrt((np.abs(h) ** 2).sum(axis=1, keepdims=True))
    return power, h


def inject_scale(mf, n, h, power):
    """Amplitude that lands a recovered SNR of 1.

    Injections have to be specified in SNR or the workload cannot be aimed at
    a threshold, and the mapping from time-domain amplitude to recovered SNR
    depends on n and on the normalisation the caller brought.  Measure it once
    against the filter rather than deriving it.
    """
    w = np.fft.ifft(np.conj(h[0])); w /= np.linalg.norm(w)
    blk = np.zeros(n, np.complex64); blk[:] = (1000.0 * w).astype(np.complex64)
    f = mf.MatchedFilter(n, 1, 1)
    f.set_templates(h[:1])
    f.set_data((np.fft.fft(blk) / n).astype(np.complex64)[None, :])
    _, _, m = f.run(binsize=n, threshold=0.0, raw=True)
    return 1000.0 / float(m[0, 0, 0])


def noise_scale(mf, n, h, series):
    """Scale that puts the filter output on noise at unit-variance components.

    That is the library's input contract, and every threshold is quoted in it.
    Unit-variance samples going in do NOT produce unit-variance output -- the
    normalisation depends on n and on how the caller scaled the spectrum -- so
    without this, "threshold 5.0" is a number with no relation to the search
    it is meant to represent.  Measured against a Rayleigh median rather than
    derived, so it cannot drift away from whatever the filter actually does.
    """
    f = mf.MatchedFilter(n, 1, 1)
    f.set_templates(h[:1])
    f.set_data((np.fft.fft(series[:n]) / n).astype(np.complex64)[None, :])
    _, _, m = f.run(binsize=1, threshold=0.0, raw=True)
    return float(np.sqrt(np.log(4.0)) / np.median(m[0, 0]))


def dataset(mf, n, ntmpl, series_len, ninject, snr_lo, snr_hi, rng,
            clusters=8, overlap=0.95):
    power, h = bank(n, ntmpl, rng, clusters, overlap)
    series = ((rng.standard_normal(series_len)
               + 1j * rng.standard_normal(series_len))
              / np.sqrt(2)).astype(np.complex64)
    series *= noise_scale(mf, n, h, series)
    scale = inject_scale(mf, n, h, power)
    # Injections are drawn from the bank itself, so each one lights up its own
    # template and its neighbours -- the co-firing a real search sees.  Their
    # SNRs straddle the threshold on purpose: a population well above it makes
    # every trigger a true one and hides whatever the gate is wasting.
    snrs = rng.uniform(snr_lo, snr_hi, ninject)
    for j in range(ninject):
        t0 = int(rng.uniform(0.02, 0.95) * (series_len - n))
        w = np.fft.ifft(np.conj(h[rng.integers(ntmpl)]))
        w /= np.linalg.norm(w)
        series[t0:t0 + n] += (snrs[j] * scale * w).astype(np.complex64)
    return power, h, series


def blocks(n, ntaps, series_len):
    valid, bad = n - ntaps + 1, ntaps // 2
    st, ws, we, t = [], [], [], 0
    while t + n <= series_len:
        st.append(t); ws.append(bad); we.append(bad + valid); t += valid
    return (np.array(st, np.uintp), np.array(ws, np.uintp),
            np.array(we, np.uintp))


def flat_reference(mf, n, h, series, st, ws, we, threshold):
    """What the full filter reports, block by block, at the same threshold.

    This is the truth the hierarchical filter has to reproduce exactly.  It
    repeats run_series' own block handling: zero-padded tail, forward
    transform, spectrum divided by n.
    """
    f = mf.MatchedFilter(n, 1, len(h))
    f.set_templates(h)
    idx = np.empty((len(st), len(h)), np.int64)
    mag = np.empty((len(st), len(h)), np.float32)
    buf = np.zeros(n, np.complex64)
    t0 = time.perf_counter()
    for b, s0 in enumerate(st):
        have = min(n, max(0, len(series) - int(s0)))
        buf[:have] = series[int(s0):int(s0) + have]
        buf[have:] = 0
        f.set_data((np.fft.fft(buf) / n).astype(np.complex64)[None, :])
        i, _, m = f.run(binsize=n, threshold=threshold,
                        window=(int(ws[b]), int(we[b])), raw=True)
        idx[b] = i[0, :, 0]
        mag[b] = m[0, :, 0]
    return idx, mag, (time.perf_counter() - t0) * 1e3


def replay(mf, path, reps, a):
    """Re-run a captured pycbc call and check it against the captured output.

    band / oversample / first stage can be overridden, which is the point: the
    capture fixes the data, the bank and the thresholds, so a sweep over the
    gate's configuration is a clean experiment with a pass/fail attached.
    """
    z = np.load(path)
    n = int(z["n_fft"])
    thr = float(z["threshold"])
    band = a.band or int(z["band"])
    fs = a.first_stage or float(z["first_stage"])
    nb = int(z["nbatch"])
    series = z["series"]
    st, ws, we = (z["starts"].astype(np.uintp), z["win_start"].astype(np.uintp),
                  z["win_end"].astype(np.uintp))

    p = mf.HierarchicalFilter(n, ndata=1, ntemplates=nb, snr=thr,
                              fd=float(z["fd"]),
                              band=band or None,
                              oversample=a.oversample if band else None,
                              taps=a.filter_taps if band else None)
    if len(z["reference"]):
        p.set_reference(z["reference"])
    p.set_templates(z["templates"])
    if fs > 0:
        p.set_first_stage(fs)

    best = float("inf")
    for _ in range(reps + 1):
        t0 = time.perf_counter()
        gi, gv, _ = p.run_series(series, st, ws, we, binsize=n,
                                 threshold=thr, raw=True)
        best = min(best, time.perf_counter() - t0)
    gi = np.array(gi[:, :, 0])
    gv = np.array(gv[:, :, 0])

    # What the flat filter costs on the same blocks, for the speedup.
    f = mf.MatchedFilter(n, 1, nb)
    f.set_templates(z["templates"])
    buf = np.zeros(n, np.complex64)
    t0 = time.perf_counter()
    for b, s0 in enumerate(z["starts"]):
        have = min(n, max(0, len(series) - int(s0)))
        buf[:have] = series[int(s0):int(s0) + have]
        buf[have:] = 0
        f.set_data((np.fft.fft(buf) / n).astype(np.complex64)[None, :])
        f.run(binsize=n, threshold=thr,
              window=(int(ws[b]), int(we[b])), raw=True)
    flat_ms = (time.perf_counter() - t0) * 1e3

    ci, cv = z["index"], z["value"]
    same = (gi >= 0) == (ci >= 0)
    both = (gi >= 0) & (ci >= 0)
    moved = both & (gi != ci)
    dv = (np.abs(gv[both] - cv[both]) / np.maximum(np.abs(cv[both]), 1e-30)
          if both.any() else np.zeros(1))

    print("matchedfilter %s  target=%s" % (mf.__version__, mf.backend()))
    print("captured from pycbc_inspiral_fir: %s" % os.path.basename(path))
    print("n=%d  threshold=%.2f  band=%d bins (%.0f Hz)  first stage %s  fd=%g"
          % (n, thr, band, float(z["band_hz"]),
             ("%.2f" % fs) if fs > 0 else "derived", float(z["fd"])))
    print("%d blocks x %d templates = %d pairs, band/oversample/taps %s\n"
          % (len(st), nb, len(st) * nb, p.config))
    print("  %-24s %10s" % ("flat filter", "%.2f ms" % flat_ms))
    print("  %-24s %10s   %.2fx" % ("hierarchical", "%.2f ms" % (best * 1e3),
                                    flat_ms / (best * 1e3)))
    print("  %-24s %10s" % ("triggered", "%.2f%%" % (100 * p.trigger_rate)))
    print("  %-24s %10d" % ("triggers pycbc got", int((ci >= 0).sum())))

    bad = []
    if not same.all():
        bad.append("%d pairs disagree on whether there is a trigger"
                   % int((~same).sum()))
    if moved.any():
        bad.append("%d triggers at a different lag" % int(moved.sum()))
    if dv.max() > 1e-5:
        bad.append("SNR differs by %.2e, beyond fp32" % dv.max())
    if (ci >= 0).sum() == 0:
        bad.append("the capture holds no triggers, so nothing is proved")
    if bad:
        print("\n  proof: *** FAILED ***")
        for b in bad:
            print("     " + b)
        return 1
    print("\n  proof: all %d triggers reproduced, same lags, SNR within %.1e"
          % (int((ci >= 0).sum()), dv.max()))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--templates", type=int, default=64)
    ap.add_argument("--taps", type=int, default=1024)
    ap.add_argument("--series", type=int, default=1 << 19)
    ap.add_argument("--threshold", type=float, default=5.0)
    ap.add_argument("--band", type=int, default=0,
                    help="0 lets the design table choose, which is what a\ncaller gets by default and where the calibration defect lives")
    ap.add_argument("--oversample", type=int, default=2)
    ap.add_argument("--filter-taps", type=int, default=8)
    ap.add_argument("--first-stage", type=float, default=0.0,
                    help="first-stage SNR; 0 uses the derived level")
    ap.add_argument("--inject", type=int, default=60,
                    help="injected signals, drawn from the bank")
    ap.add_argument("--clusters", type=int, default=8,
                    help="clusters in the bank; templates within one overlap")
    ap.add_argument("--overlap", type=float, default=0.95,
                    help="overlap of each template with its cluster seed")
    ap.add_argument("--snr-lo", type=float, default=4.5)
    ap.add_argument("--snr-hi", type=float, default=9.0)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--quick", action="store_true",
                    help="a quarter the series, for a fast edit loop")
    ap.add_argument("--isa", default="", help="force one SIMD target")
    ap.add_argument("--fixture", default="",
                    help="replay a call captured from pycbc_inspiral_fir")
    ap.add_argument("--no-profile", action="store_true")
    a = ap.parse_args(argv)
    if a.quick:
        a.series //= 4
        a.inject //= 4

    if not a.no_profile:
        os.environ["MF_HMF_PROF"] = "1"       # read when the plan is created
    import matchedfilter as mf
    if a.isa:
        mf.set_target(a.isa)

    if a.fixture:
        rc = replay(mf, a.fixture, a.reps, a)
        if not a.no_profile:
            sys.stdout.flush()
        return rc

    rng = np.random.default_rng(11)
    power, h, series = dataset(mf, a.n, a.templates, a.series, a.inject,
                               a.snr_lo, a.snr_hi, rng, a.clusters, a.overlap)
    st, ws, we = blocks(a.n, a.taps, a.series)
    npair = len(st) * a.templates

    p = mf.HierarchicalFilter(a.n, ndata=1, ntemplates=a.templates,
                              snr=a.threshold, fd=1e-3,
                              band=a.band or None,
                              oversample=a.oversample if a.band else None,
                              taps=a.filter_taps if a.band else None)
    p.set_reference(power)
    p.set_templates(h)
    if a.first_stage:
        p.set_first_stage(a.first_stage)

    fi, fm, flat_ms = flat_reference(mf, a.n, h, series, st, ws, we, a.threshold)

    best = float("inf")
    for _ in range(a.reps + 1):
        t0 = time.perf_counter()
        gi, gv, gm = p.run_series(series, st, ws, we, binsize=a.n,
                                  threshold=a.threshold, raw=True)
        best = min(best, time.perf_counter() - t0)
    gi = np.array(gi).reshape(len(st), a.templates)
    gm = np.array(gm).reshape(len(st), a.templates)
    gated_ms = best * 1e3
    rate = p.trigger_rate

    found = fi >= 0
    omitted = found & (gi < 0)
    moved = found & (gi >= 0) & (gi != fi)
    invented = (gi >= 0) & ~found
    both = found & (gi >= 0)
    relmag = (np.abs(gm[both] - fm[both]) / np.maximum(fm[both], 1e-30)
              if both.any() else np.zeros(1))

    # Internal check: the lowest first-stage level the design grid offers has
    # to report a superset of this run, with identical values where both fire.
    p.set_first_stage(0.01)
    li, lv, lm = p.run_series(series, st, ws, we, binsize=a.n,
                              threshold=a.threshold, raw=True)
    li = np.array(li).reshape(len(st), a.templates)
    lm = np.array(lm).reshape(len(st), a.templates)
    p.set_first_stage(a.first_stage if a.first_stage else None)
    lost = (gi >= 0) & (li < 0)
    drift = (gi >= 0) & (li >= 0) & ((li != gi) | (lm != gm))

    print("matchedfilter %s  target=%s" % (mf.__version__, mf.backend()))
    print("n=%d  threshold=%.1f  first stage %s  config %s"
          % (a.n, a.threshold,
             ("%.2f" % a.first_stage) if a.first_stage else "derived",
             "pinned" if a.band else "from the design table"))
    print("%d blocks x %d templates = %d pairs, %d injections, "
          "band/oversample/taps %s\n"
          % (len(st), a.templates, npair, a.inject, p.config))

    print("  %-24s %10s" % ("flat filter", "%.2f ms" % flat_ms))
    print("  %-24s %10s   %.2fx" % ("hierarchical", "%.2f ms" % gated_ms,
                                    flat_ms / gated_ms))
    print("  %-24s %10s" % ("triggered", "%.2f%%" % (100 * rate)))
    print("  %-24s %10d" % ("peaks in the flat run", int(found.sum())))
    ntrig = int(round(rate * npair))
    waste = ntrig - int(found.sum())
    print("  %-24s %10d   %.1f%% of pairs" % ("reconstructed", ntrig,
                                              100.0 * ntrig / npair))
    print("  %-24s %10d   %.1f%% of reconstructions were unnecessary"
          % ("...that found nothing", waste,
             100.0 * waste / ntrig if ntrig else 0.0))

    fails = []
    # The guarantee is probabilistic: at most `fd` false dismissals for a
    # signal of strength `snr`.  Demanding zero would fail on a budget that is
    # being met, so compare the rate, and report it either way -- a run that
    # omits nothing at all is also information.
    fdrate = omitted.sum() / found.sum() if found.sum() else 0.0
    if fdrate > 1e-3:
        fails.append("%d of %d peaks omitted, rate %.2e against a 1e-3 budget"
                     % (omitted.sum(), found.sum(), fdrate))
    if moved.any():
        fails.append("%d peaks at a different lag" % moved.sum())
    if invented.any():
        fails.append("%d peaks the flat filter does not report" % invented.sum())
    if relmag.max() > 1e-5:
        fails.append("magnitude differs by %.2e, beyond fp32" % relmag.max())
    if lost.any():
        fails.append("%d peaks lost at the lowest first stage" % lost.sum())
    if drift.any():
        fails.append("%d peaks changed at the lowest first stage" % drift.sum())
    if found.sum() == 0:
        fails.append("the flat filter found nothing, so nothing was proved:"
                     " lower --threshold or raise --inject")

    if fails:
        print("\n  proof: *** FAILED ***")
        for f in fails:
            print("     " + f)
    else:
        print("\n  proof: %d peaks, same lags, magnitudes within %.1e;"
              % (found.sum(), relmag.max()))
        print("         %d omitted (rate %.1e, budget 1.0e-03)"
              % (int(omitted.sum()), fdrate))
        print("         %d more pairs fire at the lowest first stage, none lost"
              % int(((li >= 0) & (gi < 0)).sum()))

    if not a.no_profile:
        sys.stdout.flush()
        p._mf.stats()          # prints the per-stage profile to stderr
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
