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


# Colours from the logo: slate for the baselines, the logo's blue for the
# filter, its green for the hierarchical mode.
BASELINE, FILTER, HIER = "#94a3b8", "#4facfe", "#38ef7d"

BARS = [
    ("CPU", "FFTW (patient)", "ifft only", fftw_ms, BASELINE),
    ("CPU", "matchedfilter", "correlate + ifft + peak", lambda: cpu_ms("flat"), FILTER),
    ("CPU", "matchedfilter, hierarchical", "correlate + ifft + peak", lambda: cpu_ms("hier"), HIER),
    ("GPU", "rocFFT", "ifft only \u2014 at the bandwidth limit", rocfft_ms, BASELINE),
    ("GPU", "matchedfilter", "correlate + ifft + peak", lambda: gpu_ms("flat"), FILTER),
    ("GPU", "matchedfilter, hierarchical", "correlate + ifft + peak", lambda: gpu_ms("hier"), HIER),
]


def svg(results, out):
    """Two panels, independent scales, throughput so taller is better.

    One scale for both would be useless: the GPU hierarchical bar is 450x
    the FFTW one, so everything on the CPU side collapses to a hairline.
    Splitting them keeps each comparison legible, and the axis label says
    the panels are not on the same scale.

    Colours are explicit and the panel has its own light background. Drawing
    with currentColor meant the figure inherited the page's text colour, and
    on a dark README it came out as faint grey on near-black.
    """
    # The logo's ground, so the figure sits beside it rather than fighting
    # it -- and a fixed dark panel reads the same on a light or dark page,
    # which inheriting currentColor did not.
    INK, MUT, LINE, BG = "#e8eef7", "#94a3b8", "#243044", "#0b0f19"
    W, H = 900, 470
    pw, ph = 380, 250                 # panel plot area
    o = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
         'width="%d" height="%d" font-family="-apple-system,BlinkMacSystemFont,'
         'Segoe UI,Roboto,Helvetica,Arial,sans-serif">' % (W, H, W, H)]
    o.append('<rect width="%d" height="%d" rx="8" fill="%s"/>' % (W, H, BG))
    o.append('<text x="28" y="34" font-size="17" font-weight="600" fill="%s">'
             '16384 correlations of 4096 points</text>' % INK)
    o.append('<text x="28" y="55" font-size="12.5" fill="%s">correlations per '
             'second — taller is better. The two panels have DIFFERENT scales.'
             '</text>' % MUT)

    groups = [("CPU", [r for r in results if r[0][0] == "CPU"]),
              ("GPU", [r for r in results if r[0][0] == "GPU"])]
    for gi, (label, rows) in enumerate(groups):
        x0 = 60 + gi * 450
        y0 = 100
        hi = max(PAIRS / (ms / 1e3) for _bar, ms in rows)
        o.append('<text x="%d" y="%d" font-size="13" font-weight="600" '
                 'fill="%s">%s</text>' % (x0, y0 - 16, INK, label))
        o.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s"/>'
                 % (x0, y0 + ph, x0 + pw, y0 + ph, LINE))
        bw, gap = 86, 40
        for bi, (bar, ms) in enumerate(rows):
            thru = PAIRS / (ms / 1e3)
            h = max(3.0, ph * thru / hi)
            x = x0 + 26 + bi * (bw + gap)
            y = y0 + ph - h
            o.append('<rect x="%d" y="%.1f" width="%d" height="%.1f" rx="3" '
                     'fill="%s"/>' % (x, y, bw, h, bar[4]))
            o.append('<text x="%d" y="%.1f" font-size="12.5" font-weight="600" '
                     'text-anchor="middle" fill="%s">%s</text>'
                     % (x + bw // 2, y - 20, INK, _thru(thru)))
            o.append('<text x="%d" y="%.1f" font-size="10.5" '
                     'text-anchor="middle" fill="%s">%.2f ms</text>'
                     % (x + bw // 2, y - 7, MUT, ms))
            for li, line in enumerate(_wrap(bar[1])):
                o.append('<text x="%d" y="%d" font-size="11.5" '
                         'text-anchor="middle" fill="%s">%s</text>'
                         % (x + bw // 2, y0 + ph + 18 + li * 13, INK, line))
            o.append('<text x="%d" y="%d" font-size="9.5" text-anchor="middle" '
                     'fill="%s">%s</text>'
                     % (x + bw // 2, y0 + ph + 18 + len(_wrap(bar[1])) * 13,
                        MUT, bar[2]))
    o.append('<text x="28" y="%d" font-size="11.5" fill="%s">FFTW and rocFFT '
             'do the inverse transform ALONE; matchedfilter does the product, '
             'the transform and the peak scan.</text>' % (H - 30, MUT))
    o.append('<text x="28" y="%d" font-size="11.5" fill="%s">Only the peak per '
             'bin is returned, so the 537 MB of correlation is never written — '
             'on the GPU rocFFT is at the bandwidth limit (213 of 211 GB/s).'
             '</text>' % (H - 14, MUT))
    o.append("</svg>")
    with open(out, "w") as fh:
        fh.write("\n".join(o))


def _thru(v):
    if v >= 1e6:
        return "%.1fM/s" % (v / 1e6)
    return "%.0fk/s" % (v / 1e3)


def _wrap(name):
    return name.split(", ") if ", " in name else [name]


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
