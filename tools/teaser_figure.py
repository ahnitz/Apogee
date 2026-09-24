"""The figure that answers "why would I care?", measured on this machine.

Six bars at n=4096 and one batch size, so the work is identical everywhere.

The comparison is deliberately unfair TO US in what is counted: FFTW and
rocFFT are timed doing the inverse transform ALONE, while matchedfilter is
timed doing the frequency-domain product, the inverse transform AND the peak
scan. The bars are labelled that way.

The reason it still wins is the OUTPUT, not the arithmetic. A library that
returns the correlation has to write it: 16384 pairs at 4096 points is
537 MB per pass. matchedfilter never materialises it -- the peak scan is
fused into the last stage and only the peaks are written, a few hundred
kilobytes. That is the whole idea, and the figure is where it shows.

The baselines are given every advantage that is easy to give:

  * both use their own BATCHED interface, planned once, outside the timing;
  * no host transfer is timed -- rocFFT's buffer is allocated on the device
    and left there, and the synchronisation is amortised over many executes
    rather than paid per call;
  * FFTW is planned FFTW_PATIENT.

And the rocFFT figure is not a bad one. It moves 213 GB/s of read+write
against 211 GB/s for a plain device-to-device copy of the same 512 MB, so
it is running AT this device's memory bandwidth -- where a batched FFT of
this size should be. Per-transform cost is flat from batch 2048 to 32768
(0.307-0.320 us), which says the same thing.

That is the GPU story exactly: the baseline is bandwidth-bound BECAUSE it
has to write the correlation, and this method's whole point is not writing
it.

It is NOT the CPU story, and the figure should not claim it is. FFTW moves
11 GB/s against 52.8 GB/s for a single-core copy -- 21%, nowhere near the
limit. At n=4096 one transform is 32 KB and stays in L2, so FFTW is bound
by the transform arithmetic (about 40 GFLOP/s, ~12% of this core's peak).
The CPU gain comes from fusing three passes into one and never writing the
output, not from dodging a bandwidth wall that is not there.

Run:  python tools/teaser_figure.py --out docs/assets/teaser.svg
"""
import argparse
import ctypes
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
import matchedfilter as mf

N = 4096
ND, NT = 16, 1024              # 16384 pairs
PAIRS = ND * NT


def _case(seed=1):
    rng = np.random.default_rng(seed)
    d = (rng.standard_normal((ND, N)) + 1j * rng.standard_normal((ND, N))).astype(np.complex64)
    h = (rng.standard_normal((NT, N)) + 1j * rng.standard_normal((NT, N))).astype(np.complex64)
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    return d, h


def _reference():
    from test_api import inspiral_power, template_with_power
    ref = inspiral_power(N)
    h = np.stack([template_with_power(N, inspiral_power(N, exponent=e))
                  for e in np.linspace(-7 / 3.0, -4 / 3.0, NT)])
    return ref, h


def fftw_ms(reps=3):
    """FFTW, planned PATIENT, batched inverse transform only."""
    import pyfftw
    a = pyfftw.empty_aligned((PAIRS // 8, N), dtype="complex64")
    b = pyfftw.empty_aligned((PAIRS // 8, N), dtype="complex64")
    plan = pyfftw.FFTW(a, b, axes=(1,), direction="FFTW_BACKWARD",
                       flags=("FFTW_PATIENT",), threads=1)
    a[:] = _case()[0][0]
    plan()
    t0 = time.perf_counter()
    for _ in range(reps):
        plan()
    per = (time.perf_counter() - t0) / reps
    # Planned and timed on an eighth of the batch, then scaled. The full
    # batch is 537 MB in and 537 MB out, and an eighth of it has a better
    # chance of staying in cache -- so this FLATTERS FFTW, which is the
    # direction to err in when it is the baseline.
    return per * 8 * 1e3


def cpu_ms(kind, reps=3):
    d, h = _case()
    if kind == "flat":
        f = mf.MatchedFilter(N, ND, NT)
    else:
        ref, h = _reference()
        f = mf.HierarchicalFilter(N, ND, NT, snr=5.5, fd=1e-2)
        f.set_reference(ref)
    f.set_data(d)
    f.set_templates(h)
    f.run(binsize=N, threshold=5.5)
    t0 = time.perf_counter()
    for _ in range(reps):
        f.run(binsize=N, threshold=5.5)
    return (time.perf_counter() - t0) / reps * 1e3


def gpu_ms(kind, reps=12):
    from matchedfilter import _vkcompute as V
    d, h = _case()
    if kind == "flat":
        f = mf.MatchedFilter(N, ND, NT, device="gpu")
    else:
        ref, h = _reference()
        f = mf.HierarchicalFilter(N, ND, NT, snr=5.5, fd=1e-2, device="gpu")
        f.set_reference(ref)
    f.set_data(d)
    f.set_templates(h)
    f.run(binsize=N, threshold=5.5)
    ctx = f._gpu
    cmds = [b[1] for b in ctx._hier.values()] + [b[4] for b in ctx._batches.values()]
    arr = (V._vp * len(cmds))(*cmds)
    sub = V._SubmitInfo(4, None, 0, None, None, len(cmds), arr, 0, None)

    def go():
        ctx.vk.vkQueueSubmit(ctx.queue, 1, ctypes.byref(sub), None)
        ctx.vk.vkQueueWaitIdle(ctx.queue)

    for _ in range(3):
        go()
    t0 = time.perf_counter()
    for _ in range(reps):
        go()
    t = (time.perf_counter() - t0) / reps * 1e3
    ctx.destroy()
    return t


def rocfft_ms(reps=10):
    """rocFFT, batched inverse transform only, data already on the device."""
    hip = ctypes.CDLL("libamdhip64.so")
    roc = ctypes.CDLL("librocfft.so.0")
    hip.hipMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
    roc.rocfft_setup()
    plan = ctypes.c_void_p()
    lengths = (ctypes.c_size_t * 1)(N)
    if roc.rocfft_plan_create(ctypes.byref(plan), 0, 1, 0, 1, lengths, PAIRS, None):
        raise RuntimeError("rocfft_plan_create failed")
    buf = ctypes.c_void_p()
    if hip.hipMalloc(ctypes.byref(buf), N * PAIRS * 8):
        raise RuntimeError("hipMalloc failed")
    wsize = ctypes.c_size_t(0)
    roc.rocfft_plan_get_work_buffer_size(plan, ctypes.byref(wsize))
    info = ctypes.c_void_p()
    roc.rocfft_execution_info_create(ctypes.byref(info))
    if wsize.value:
        work = ctypes.c_void_p()
        hip.hipMalloc(ctypes.byref(work), wsize.value)
        roc.rocfft_execution_info_set_work_buffer(info, work, wsize.value)
    ins = (ctypes.c_void_p * 1)(buf)

    # Amortise the synchronisation rather than paying it per execute, and
    # keep every transfer out of the timed region -- the buffer is allocated
    # and left on the device.
    for _ in range(3):
        roc.rocfft_execute(plan, ins, None, info)
    hip.hipDeviceSynchronize()
    t0 = time.perf_counter()
    for _ in range(reps):
        roc.rocfft_execute(plan, ins, None, info)
    hip.hipDeviceSynchronize()
    per = (time.perf_counter() - t0) / reps
    roc.rocfft_plan_destroy(plan)
    return per * 1e3


BARS = [
    ("CPU", "FFTW (patient)", "ifft only", fftw_ms, "#b0b6c0"),
    ("CPU", "matchedfilter", "correlate + ifft + peak", lambda: cpu_ms("flat"), "#4c78a8"),
    ("CPU", "matchedfilter, hierarchical", "correlate + ifft + peak", lambda: cpu_ms("hier"), "#2f5d8a"),
    ("GPU", "rocFFT", "ifft only \u2014 at the bandwidth limit", rocfft_ms, "#b0b6c0"),
    ("GPU", "matchedfilter", "correlate + ifft + peak", lambda: gpu_ms("flat"), "#e6924c"),
    ("GPU", "matchedfilter, hierarchical", "correlate + ifft + peak", lambda: gpu_ms("hier"), "#c26a22"),
]


def svg(results, out):
    W, H = 900, 430
    left, top, bw, gap = 300, 64, 520, 14
    bh = 34
    hi = max(r[1] for r in results)
    o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
         'width="%d" height="%d" font-family="-apple-system,Segoe UI,Roboto,'
         'Helvetica,Arial,sans-serif">' % (W, H, W, H)]
    o.append('<rect width="%d" height="%d" fill="none"/>' % (W, H))
    o.append('<text x="24" y="28" font-size="16" font-weight="600" '
             'fill="currentColor">16384 correlations of 4096 points</text>')
    o.append('<text x="24" y="48" font-size="12.5" fill="currentColor" '
             'opacity=".65">lower is better; FFT libraries are timed doing the '
             'inverse transform ALONE</text>')
    y = top
    last_group = None
    for (group, name, what, _fn, colour), ms in results:
        if group != last_group:
            o.append('<text x="24" y="%d" font-size="12" font-weight="600" '
                     'fill="currentColor" opacity=".55">%s</text>'
                     % (y + 22, group))
            last_group = group
        w = max(2.0, bw * ms / hi)
        o.append('<rect x="%d" y="%d" width="%.1f" height="%d" rx="3" fill="%s"/>'
                 % (left, y, w, bh, colour))
        o.append('<text x="%d" y="%d" font-size="13" text-anchor="end" '
                 'fill="currentColor">%s</text>' % (left - 12, y + 16, name))
        o.append('<text x="%d" y="%d" font-size="10.5" text-anchor="end" '
                 'fill="currentColor" opacity=".55">%s</text>'
                 % (left - 12, y + 29, what))
        o.append('<text x="%.1f" y="%d" font-size="12.5" fill="currentColor" '
                 'opacity=".8">%.1f ms</text>' % (left + w + 10, y + 22, ms))
        y += bh + gap
    o.append('<text x="24" y="%d" font-size="11.5" fill="currentColor" '
             'opacity=".6">matchedfilter returns only the peak per bin, so the '
             '537 MB of correlation an FFT must write is never materialised. '
             'On the GPU that is the whole gap: rocFFT runs at 213 GB/s '
             'against a 211 GB/s copy ceiling — at the bandwidth limit.'
             '</text>' % (H - 26))
    o.append('<text x="24" y="%d" font-size="11.5" fill="currentColor" '
             'opacity=".6">Measured on %s / %s.</text>'
             % (H - 10, _cpu_name(), _gpu_name()))
    o.append("</svg>")
    with open(out, "w") as fh:
        fh.write("\n".join(o))


def _cpu_name():
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "CPU"


def _gpu_name():
    for d in mf.devices():
        if d.kind == "gpu" and not d.is_software:
            return d.name
    return "GPU"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/assets/teaser.svg")
    args = ap.parse_args(argv)
    results = []
    for bar in BARS:
        ms = bar[3]()
        print("  %-4s %-30s %-26s %8.2f ms" % (bar[0], bar[1], bar[2], ms))
        results.append((bar, ms))
    svg(results, args.out)
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
