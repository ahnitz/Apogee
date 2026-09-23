"""Benchmark the Apple GPU back end against the CPU filter (and MLX, if present).

    python -m matchedfilter.benchmark_metal
    python -m matchedfilter.benchmark_metal --n 4096 65536 --threads 4 --json out.json

For each length the same random spectra go through

  cpu        matchedfilter.MatchedFilter, one thread -- the library's design point
  cpu xN     the same, N threads each running its own plan over a share of the
             templates (the C call releases the GIL), i.e. what a caller gets by
             parallelising over the bank as the README suggests
  metal      matchedfilter.metal.MatchedFilter
  mlx        the obvious MLX formulation -- ifft of the products, |.|, binned
             argmax -- which has to materialise every correlation; included to
             show why the GPU back end is a fused Metal kernel instead

and the GPU's peaks are checked against the CPU's before anything is timed:
a timing of a wrong answer is worthless.  Times are the median of --reps runs,
per pair, wall clock including submission; "gpu" is the kernels alone as the
GPU reports them.
"""
import argparse
import json
import platform
import threading
import time

import numpy as np

import matchedfilter as mf
from matchedfilter import metal

try:
    import mlx.core as mx
except ImportError:          # optional
    mx = None


def spectra(shape, seed):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(shape) + 1j * rng.standard_normal(shape)).astype(np.complex64)


def median_time(fn, reps):
    fn()                      # warm: plans, pipelines, caches, GPU clocks
    ts = []
    for _ in range(reps):
        t = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t)
    return float(np.median(ts))


def check(n, g, c, z_of):
    """GPU peaks against the CPU's: same crossings and lags up to ties."""
    gi, ci = g["index"], c["index"]
    bad = np.argwhere(gi != ci)
    for d, t, b in bad:
        a = np.abs(z_of(d, t))
        if gi[d, t, b] < 0 or ci[d, t, b] < 0 or \
           abs(a[gi[d, t, b]] - a[ci[d, t, b]]) > 3e-5 * a[ci[d, t, b]]:
            raise AssertionError("GPU disagrees with CPU at n=%d pair (%d,%d) bin %d" % (n, d, t, b))
    err = np.max(np.abs(g["magnitude"] - c["magnitude"]) / np.maximum(c["magnitude"], 1e-30))
    return float(err), len(bad)


def run_cpu_threads(D, H, nthreads, kw):
    """nthreads plans, each over a contiguous share of the templates."""
    n, nd, nt = D.shape[1], D.shape[0], H.shape[0]
    cuts = np.linspace(0, nt, nthreads + 1).astype(int)
    plans = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b > a:
            p = mf.MatchedFilter(n, nd, b - a)
            p.set_data(D)
            p.set_templates(H[a:b])
            plans.append(p)

    def go():
        ts = [threading.Thread(target=p.run, kwargs=kw) for p in plans]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    return go


def run_mlx(D, H, binsize):
    """Binned max of |IFFT(D conj H)| with MLX, in pair chunks to bound memory."""
    n, nd, nt = D.shape[1], D.shape[0], H.shape[0]
    Dm, Hm = mx.array(D), mx.conj(mx.array(H))
    per = max(1, (256 << 20) // (n * 8 * nd))     # templates per chunk, ~256 MiB of z

    def go():
        outs = []
        for t0 in range(0, nt, per):
            z = mx.fft.ifft(Dm[:, None, :] * Hm[None, t0:t0 + per, :], axis=-1) * n
            a = mx.abs(z).reshape(nd, -1, n // binsize, binsize)
            outs += [mx.argmax(a, axis=-1), mx.max(a, axis=-1)]
        mx.eval(*outs)
    return go


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, nargs="+",
                    default=[1024, 4096, 16384, 65536, 262144, 1 << 20])
    ap.add_argument("--data", type=int, default=16)
    ap.add_argument("--templates", type=int, default=None,
                    help="default: enough for ~2^26 samples of GPU work per run")
    ap.add_argument("--threads", type=int, default=4, help="CPU threads for the cpu xN column")
    ap.add_argument("--reps", type=int, default=7)
    ap.add_argument("--no-mlx", action="store_true")
    ap.add_argument("--json", help="write the results here")
    a = ap.parse_args(argv)
    if not metal.available():
        raise SystemExit("no Metal GPU back end on this machine")

    print("machine: %s  cpu kernel: %s  gpu: %s" % (platform.platform(), mf.backend(), metal.device()))
    print("per pair, median of %d; bins of n/16, threshold high enough that nothing crosses" % a.reps)
    hdr = "%9s %6s %10s %10s %10s %10s %10s %8s %8s" % (
        "n", "pairs", "cpu us", "cpu x%d us" % a.threads, "metal us", "gpu us",
        "mlx us", "vs cpu", "vs x%d" % a.threads)
    print(hdr)
    rows = []
    for n in a.n:
        nd = a.data
        nt = a.templates or max(2, min(1024, (1 << 26) // (n * nd)))
        D, H = spectra((nd, n), 1), spectra((nt, n), 2)
        binsize = n // 16
        kw = dict(binsize=binsize, threshold=0.0)

        g = metal.MatchedFilter(n, nd, nt)
        g.set_data(D)
        g.set_templates(H)
        c = mf.MatchedFilter(n, nd, nt)
        c.set_data(D)
        c.set_templates(H)
        # correctness first, on every pair
        gp, cp = g.run(**kw).copy(), c.run(**kw)
        err, ties = check(n, gp, cp, lambda d, t: np.fft.ifft(
            D[d].astype(np.complex128) * np.conj(H[t].astype(np.complex128))) * n)

        kw = dict(binsize=binsize, threshold=1e30, raw=True)
        P = nd * nt
        t_cpu = median_time(lambda: c.run(**kw), max(2, a.reps // 2)) / P
        t_thr = median_time(run_cpu_threads(D, H, a.threads, kw), max(2, a.reps // 2)) / P
        gpu_s = []

        def gpu_run():
            g.run(**kw)
            gpu_s.append(metal._metal.last_gpu_seconds())
        t_gpu = median_time(gpu_run, a.reps) / P
        t_kern = float(np.median(gpu_s[1:])) / P
        t_mlx = float("nan")
        if mx is not None and not a.no_mlx:
            t_mlx = median_time(run_mlx(D, H, binsize), max(2, a.reps // 2)) / P
        row = dict(n=n, pairs=P, cpu_us=t_cpu * 1e6, cpu_threads=a.threads,
                   cpu_threads_us=t_thr * 1e6, metal_us=t_gpu * 1e6,
                   metal_kernel_us=t_kern * 1e6, mlx_us=t_mlx * 1e6,
                   speedup_vs_cpu=t_cpu / t_gpu, speedup_vs_threads=t_thr / t_gpu,
                   max_rel_err_vs_cpu=err, tied_lags=ties, config=g.config)
        rows.append(row)
        print("%9d %6d %10.3f %10.3f %10.3f %10.3f %10.3f %7.1fx %7.1fx" % (
            n, P, row["cpu_us"], row["cpu_threads_us"], row["metal_us"],
            row["metal_kernel_us"], row["mlx_us"], row["speedup_vs_cpu"],
            row["speedup_vs_threads"]))
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(dict(machine=platform.platform(), cpu_kernel=mf.backend(),
                           gpu=metal.device(), rows=rows), fh, indent=1)


if __name__ == "__main__":
    main()
