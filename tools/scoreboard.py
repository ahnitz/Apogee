"""CPU and GPU, flat and hierarchical, at every supported length.

One table, run the same way every time, so progress is comparable across
changes rather than re-argued each time.

GPU numbers are COMPUTE ONLY: the data is already resident and the host
copies and readback are excluded, because the target case is data that
already lives on the device (a torch tensor, say). CPU numbers are the whole
call, which is all a CPU has.

The workload is deliberately realistic. Templates are unit-norm so a peak
reads directly as an SNR, the threshold is 5.5, and the hierarchical mode
gets a reference with an inspiral-like slope -- a flat reference gives the
coarse pass nothing to exploit and the comparison becomes meaningless.
"""
import argparse
import ctypes
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
import matchedfilter as mf
from matchedfilter import _vkcompute as V
from test_api import inspiral_power, template_with_power

SIZES = (1024, 2048, 4096, 8192, 16384)
THRESHOLD = 5.5


def workload(n, nd, nt, seed=1):
    rng = np.random.default_rng(seed)
    d = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    ref = inspiral_power(n)
    h = np.stack([template_with_power(n, inspiral_power(n, exponent=e))
                  for e in np.linspace(-7 / 3.0, -4 / 3.0, nt)])
    return d, h, ref


def cpu_ms(kind, n, nd, nt, reps=3):
    d, h, ref = workload(n, nd, nt)
    if kind == "flat":
        f = mf.MatchedFilter(n, nd, nt)
    else:
        f = mf.HierarchicalFilter(n, nd, nt, snr=THRESHOLD, fd=1e-2)
        f.set_reference(ref)
    f.set_data(d)
    f.set_templates(h)
    f.run(binsize=n, threshold=THRESHOLD)
    t0 = time.perf_counter()
    for _ in range(reps):
        f.run(binsize=n, threshold=THRESHOLD)
    return (time.perf_counter() - t0) / reps * 1e3


def _submit_only(ctx, reps):
    """Replay every recorded command buffer: compute with no host traffic."""
    vk = ctx.vk
    cmds = [b[4] for b in ctx._batches.values()]
    arr = (V._vp * len(cmds))(*cmds)
    sub = V._SubmitInfo(4, None, 0, None, None, len(cmds), arr, 0, None)

    def go():
        vk.vkQueueSubmit(ctx.queue, 1, ctypes.byref(sub), None)
        vk.vkQueueWaitIdle(ctx.queue)

    for _ in range(3):
        go()
    t0 = time.perf_counter()
    for _ in range(reps):
        go()
    return (time.perf_counter() - t0) / reps * 1e3


def gpu_full_ms(kind, n, nd, nt, reps=6):
    """The whole run() call, host decisions included.

    For the hierarchical mode this is the number that matters and the
    compute-only one flatters it: replaying the recorded command buffers
    skips the coarse-result readback and the survivor selection, which are
    a real serialisation between the coarse pass and the refinement.
    """
    d, h, ref = workload(n, nd, nt)
    if kind == "flat":
        f = mf.MatchedFilter(n, nd, nt, device="gpu")
    else:
        f = mf.HierarchicalFilter(n, nd, nt, snr=THRESHOLD, fd=1e-2, device="gpu")
        f.set_reference(ref)
    f.set_data(d)
    f.set_templates(h)
    f.run(binsize=n, threshold=THRESHOLD)
    t0 = time.perf_counter()
    for _ in range(reps):
        f.run(binsize=n, threshold=THRESHOLD)
    t = (time.perf_counter() - t0) / reps * 1e3
    f._gpu.destroy()
    return t


def gpu_ms(kind, n, nd, nt, reps=12):
    d, h, ref = workload(n, nd, nt)
    if kind == "flat":
        f = mf.MatchedFilter(n, nd, nt, device="gpu")
    else:
        f = mf.HierarchicalFilter(n, nd, nt, snr=THRESHOLD, fd=1e-2, device="gpu")
        f.set_reference(ref)
    f.set_data(d)
    f.set_templates(h)
    f.run(binsize=n, threshold=THRESHOLD)          # record everything once
    t = _submit_only(f._gpu, reps)
    rate = f.refine_rate if kind == "hier" else None
    f._gpu.destroy()
    return t, rate


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=int, default=0,
                    help="pairs per size; default scales as 2^26/n, min 8192")
    args = ap.parse_args(argv)

    print("threshold %.1f, GPU compute-only (data resident), one AVX-512 core"
          % THRESHOLD)
    print()
    print("  GPU flat/hier are compute-only; (end) is the whole call including")
    print("  the host round trips the hierarchical path still makes.")
    print()
    print("     n   pairs |    CPU flat   CPU hier |   GPU flat   GPU hier  hier(end) |"
          " flat x  hier x  hier(end)")
    print("  " + "-" * 104)
    for n in SIZES:
        pairs = args.pairs or max(8192, 2 ** 26 // n)
        nd = 16
        nt = pairs // nd
        cf = cpu_ms("flat", n, nd, nt)
        ch = cpu_ms("hier", n, nd, nt)
        gf, _ = gpu_ms("flat", n, nd, nt)
        gh, rate = gpu_ms("hier", n, nd, nt)
        ge = gpu_full_ms("hier", n, nd, nt)
        print("  %6d %7d | %8.2f ms %8.2f ms | %8.3f ms %8.3f ms %8.3f ms |"
              " %5.1fx %6.1fx %8.1fx"
              % (n, pairs, cf, ch, gf, gh, ge, cf / gf, ch / gh, ch / ge))
    print()
    print("  target: 50x or better in both GPU columns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
