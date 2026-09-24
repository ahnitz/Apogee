#!/usr/bin/env python3
"""matchedfilter on a GPU, end to end. Run it: python examples/gpu_quickstart.py

Three things, in the order you meet them: which device you get, a batch
filtered on it, and a whole time series filtered in one call per segment.

No arguments. It prints CPU and GPU side by side so the number means
something -- a us/pair figure on its own does not.
"""
import time

import numpy as np

import matchedfilter as mf

N, NDATA, NTMPL = 4096, 16, 256


def main():
    # ---- 1. what this machine has -------------------------------------
    # device="auto" takes a real GPU when there is one and the CPU otherwise.
    # A software rasteriser does NOT count as one: it would be far slower
    # than the CPU backend it displaced.
    print("devices:")
    for d in mf.devices():
        print("  %-4s %-42s%s" % (d.kind, d.name[:42],
                                  "  (software)" if d.is_software else ""))

    rng = np.random.default_rng(0)
    # Spectra come in pre-divided by n. matchedfilter's inverse transform is
    # unnormalised, which is pycbc's convention too; n is a power of two so
    # the scaling is exact either side of the transform.
    data = (rng.standard_normal((NDATA, N))
            + 1j * rng.standard_normal((NDATA, N))).astype(np.complex64) / N
    tmpl = (rng.standard_normal((NTMPL, N))
            + 1j * rng.standard_normal((NTMPL, N))).astype(np.complex64)
    tmpl /= np.linalg.norm(tmpl, axis=1, keepdims=True)

    # ---- 2. a batch ---------------------------------------------------
    # NDATA segments against NTMPL templates is one call. The batch is the
    # point: one segment against a large bank is the worst shape to hand a
    # GPU, because the bank gets streamed once per segment.
    print("\n%-6s %-40s %12s" % ("device", "name", "us/pair"))
    peaks = None
    for want in ("cpu", "auto"):
        f = mf.MatchedFilter(N, NDATA, NTMPL, device=want)
        f.set_data(data)
        f.set_templates(tmpl)
        f.run(binsize=N, threshold=0.0)                  # warm up
        t0 = time.perf_counter()
        for _ in range(5):
            peaks = f.run(binsize=N, threshold=0.0)
        per = (time.perf_counter() - t0) / 5 / (NDATA * NTMPL)
        print("%-6s %-40s %10.2f" % (want, f.device.name[:40], per * 1e6))

    # peaks is (ndata, ntemplates, nbins) with fields "index" (the lag) and
    # "value" (complex). For the magnitude take np.abs(peaks["value"]).
    # A bin nothing crossed comes back as index -1, so bin j is always at
    # slot j and you can index by frequency without searching.
    print("\nloudest pair 0/0: lag %d, |value| %.5f"
          % (peaks["index"][0, 0, 0], abs(peaks["value"][0, 0, 0])))

    # ---- 3. a whole series --------------------------------------------
    # You own the overlap-save arithmetic -- where each block starts and
    # which span of its output is valid. matchedfilter executes that plan in
    # one call, which is what removes the per-block round trip.
    ntaps, nblocks = 451, 12
    step = N - ntaps + 1
    ns = N + step * nblocks
    series = (rng.standard_normal(ns)
              + 1j * rng.standard_normal(ns)).astype(np.complex64)
    starts = (np.arange(nblocks) * step).astype(np.uintp)
    win_start = np.full(nblocks, ntaps // 2, dtype=np.uintp)
    win_end = np.full(nblocks, ntaps // 2 + step, dtype=np.uintp)

    g = mf.MatchedFilter(N, nblocks, NTMPL, device="auto")
    g.set_templates(tmpl)
    out = g.run_series(series, starts, win_start, win_end,
                       binsize=N, threshold=0.0)
    print("run_series on %s -> %s (blocks, templates, bins)"
          % (g.device.name[:36], out.shape))

    # The returned arrays are reused buffers: the next call overwrites them.
    # Copy anything that has to outlive it.


if __name__ == "__main__":
    main()
