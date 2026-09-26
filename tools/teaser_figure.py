"""Measure the teaser on this machine, including all three FDR budgets.

Matchedfilter times warm public run() calls, including GPU synchronization,
readback and result assembly. All filter bars use the same Gaussian-noise
input and a bank whose power profile matches the reference. FFTW and rocFFT
are full-batch inverse-transform-only baselines: they do less computation
but materialize the correlation. Plan creation and input upload are excluded.

Run: python tools/teaser_figure.py --out docs/assets/teaser.svg
Writes SVG, PNG and the underlying JSON measurements. Requires pyfftw,
matplotlib and the AMD rocFFT/HIP runtime for the external baselines.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
import matchedfilter as mf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
N, ND, NT = 4096, 16, 1024
PAIRS = ND * NT
BUDGETS = (1e-2, 1e-3, 1e-4)
_DETAILS = {}


def _reference():
    from test_api import inspiral_power
    ref = inspiral_power(N)
    rng = np.random.default_rng(19)
    h = (np.sqrt(ref) * np.exp(2j*np.pi*rng.random((NT, N)))).astype(np.complex64)
    h /= np.linalg.norm(h, axis=1, keepdims=True)
    return ref, h


def _case(seed=1):
    rng = np.random.default_rng(seed)
    d = (rng.standard_normal((ND, N)) + 1j*rng.standard_normal((ND, N))).astype(np.complex64)
    return d, _reference()[1]


def _timed(fn, reps):
    """Sustained warmup and block medians; preserve variability for review.

    Three calls were insufficient to establish steady GPU clocks. Blocks
    also avoid giving a microsecond-scale timer sample undue weight. This
    cannot make a concurrently loaded machine suitable for benchmarking.
    """
    until = time.perf_counter() + .5
    while time.perf_counter() < until:
        fn()
    values = []
    counts = []
    for _ in range(reps):
        start = time.perf_counter()
        count = 0
        while time.perf_counter() - start < .05:
            fn()
            count += 1
        values.append((time.perf_counter()-start)*1000/count)
        counts.append(count)
    _timed.details = dict(block_ms=values, calls_per_block=counts,
                          min_ms=min(values), max_ms=max(values))
    return float(np.median(values))


def fftw_ms(reps=7):
    """Full batch, one CPU thread, PATIENT; no inverse-normalization pass."""
    import pyfftw
    a = pyfftw.empty_aligned((PAIRS, N), dtype='complex64')
    b = pyfftw.empty_aligned((PAIRS, N), dtype='complex64')
    plan = pyfftw.FFTW(a, b, axes=(1,), direction='FFTW_BACKWARD',
                       flags=('FFTW_PATIENT',), threads=1, planning_timelimit=15.0)
    a[:] = _case()[0][0]
    return _timed(plan.execute, reps)


def _filter_ms(kind, device, reps, fd):
    d, h = _case()
    if kind == 'flat':
        f = mf.MatchedFilter(N, ND, NT, device=device)
    else:
        ref, h = _reference()
        f = mf.HierarchicalFilter(N, ND, NT, snr=5.5, fd=fd, device=device)
        f.set_reference(ref)
    f.set_data(d); f.set_templates(h)
    try:
        ms = _timed(lambda: f.run(binsize=N, threshold=5.5), reps)
        if kind == 'hier' and hasattr(f, 'config'):
            _DETAILS[(device, fd)] = {'band': f.config[0], 'taps': f.config[1],
                                      'refine_rate': f.refine_rate}
        return ms
    finally:
        ctx = getattr(f, '_gpu', None)
        if ctx is not None:
            ctx.destroy()


def cpu_ms(kind, reps=7, fd=1e-2):
    return _filter_ms(kind, 'cpu', reps, fd)


def gpu_ms(kind, reps=15, fd=1e-2):
    return _filter_ms(kind, 'gpu', reps, fd)


def rocfft_ms(reps=7):
    """Full-batch in-place rocFFT, amortized sync, initialized resident data."""
    hip = ctypes.CDLL('libamdhip64.so')
    roc = ctypes.CDLL('librocfft.so.0')
    vp, sz, integer = ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int
    signatures = {
        'rocfft_plan_create': [ctypes.POINTER(vp), integer, integer, integer, sz,
                               ctypes.POINTER(sz), sz, vp],
        'rocfft_plan_get_work_buffer_size': [vp, ctypes.POINTER(sz)],
        'rocfft_execution_info_create': [ctypes.POINTER(vp)],
        'rocfft_execution_info_set_work_buffer': [vp, vp, sz],
        'rocfft_execute': [vp, ctypes.POINTER(vp), ctypes.POINTER(vp), vp],
        'rocfft_plan_destroy': [vp], 'rocfft_execution_info_destroy': [vp],
        'rocfft_setup': [], 'rocfft_cleanup': []}
    for name, args in signatures.items():
        getattr(roc, name).argtypes = args
        getattr(roc, name).restype = integer
    hip.hipMalloc.argtypes = [ctypes.POINTER(vp), sz]
    hip.hipMemset.argtypes = [vp, integer, sz]
    hip.hipFree.argtypes = [vp]
    hip.hipDeviceSynchronize.argtypes = []
    def checked(value, name):
        if value:
            raise RuntimeError('%s failed: %d' % (name, value))
    plan, buf, work, info = vp(), vp(), vp(), vp()
    checked(roc.rocfft_setup(), 'rocfft_setup')
    try:
        lengths = (sz * 1)(N)
        checked(roc.rocfft_plan_create(ctypes.byref(plan), 0, 1, 0, 1,
                                      lengths, PAIRS, None), 'rocfft_plan_create')
        checked(hip.hipMalloc(ctypes.byref(buf), N*PAIRS*8), 'hipMalloc')
        # Zero is invariant under repeated unnormalized inverse transforms;
        # uninitialized or repeatedly amplified data can become NaN/Inf.
        checked(hip.hipMemset(buf, 0, N*PAIRS*8), 'hipMemset')
        size = sz()
        checked(roc.rocfft_plan_get_work_buffer_size(plan, ctypes.byref(size)), 'work size')
        checked(roc.rocfft_execution_info_create(ctypes.byref(info)), 'execution info')
        if size.value:
            checked(hip.hipMalloc(ctypes.byref(work), size.value), 'work allocation')
            checked(roc.rocfft_execution_info_set_work_buffer(info, work, size), 'work buffer')
        ins = (vp * 1)(buf)
        def batch():
            for _ in range(8):
                checked(roc.rocfft_execute(plan, ins, None, info), 'rocfft_execute')
            checked(hip.hipDeviceSynchronize(), 'hipDeviceSynchronize')
        return _timed(batch, reps) / 8
    finally:
        if info: roc.rocfft_execution_info_destroy(info)
        if plan: roc.rocfft_plan_destroy(plan)
        if work: hip.hipFree(work)
        if buf: hip.hipFree(buf)
        roc.rocfft_cleanup()


def _cpu_name():
    try:
        for line in Path('/proc/cpuinfo').read_text().splitlines():
            if line.startswith('model name'):
                return line.split(':', 1)[1].strip()
    except OSError:
        pass
    return 'CPU'


def _gpu_name():
    for device in mf.devices():
        if device.kind == 'gpu' and not device.is_software:
            return device.name
    return 'GPU'


def plot(report, out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'svg.fonttype': 'none'})
    bg, fg, muted = '#0b0f19', '#e8eef7', '#adb9ca'
    colors = ['#94a3b8', '#4facfe', '#38ef7d', '#28c4a7', '#50a798']
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.8), facecolor=bg)
    fig.subplots_adjust(left=.06, right=.98, top=.73, bottom=.29, wspace=.22)
    fig.text(.04, .95, '16,384 correlations × 4,096 points', color=fg, size=18, weight='bold')
    fig.text(.04, .90, 'Throughput · higher is better · CPU and GPU use different scales', color=muted, size=11)
    fig.text(.04, .852, 'Same matched-profile bank and Gaussian noise · SNR 5.5 · full lag window', color=muted, size=10)
    for ax, device, name in zip(axes, ['cpu','gpu'], [report['cpu'],report['gpu']]):
        ax.set_facecolor(bg)
        rows = [r for r in report['rows'] if r['device']==device]
        throughput = [PAIRS / (r['ms'] / 1000) for r in rows]
        # Overlay from largest to smallest, all measured from zero. The
        # visible segments are increments, not independent throughputs.
        for i, (row, value) in enumerate(zip(rows[:2], throughput[:2])):
            ax.bar(i, value, color=colors[i], width=.65, zorder=3)
            inside = (i == 1 and min(throughput[2:]) - value < max(throughput)*.18)
            ax.text(i, value*.5 if inside else value,
                    f"{value/1e6:.2f}M/s\n{row['ms']:.2f} ms", ha='center',
                    va='center' if inside else 'bottom', color=bg if inside else fg,
                    size=9 if inside else 10, linespacing=1.4)
        hierarchical = sorted(zip(rows[2:], throughput[2:], colors[2:]),
                              key=lambda item: item[1], reverse=True)
        for row, value, color in hierarchical:
            ax.bar(2.2, value, color=color, width=.8, zorder=3)
            ax.plot([1.64, 1.8], [value, value], color=color, lw=1, zorder=4)
            budget = {1e-2:'10⁻²', 1e-3:'10⁻³', 1e-4:'10⁻⁴'}[row['fd']]
            ax.text(1.58, value, f"{budget}  {value/1e6:.2f}M/s · {row['ms']:.2f} ms",
                    ha='right', va='center', color=fg, size=9)
        ax.set_xlim(-.55, 2.95)
        ax.set_ylim(0, max(throughput)*1.27)
        ax.set_xticks([0, 1, 2.2], [rows[0]['label'], 'Flat', 'Hierarchical'],
                      color=fg, size=10)
        ax.tick_params(axis='x', length=0, pad=8)
        ax.tick_params(axis='y', colors=muted, labelsize=9)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, pos: f'{v/1e6:g}M'))
        ax.yaxis.set_major_locator(MaxNLocator(4))
        ax.grid(axis='y', color='#243044', zorder=0)
        for spine in ax.spines.values(): spine.set_visible(False)
        ax.set_title(device.upper() + '  ·  ' + name.split(' w/')[0].replace('AMD ',''),
                     color=fg, size=11, loc='left', pad=16)
    fig.text(.04, .15, 'Hierarchical boundaries show total throughput at each FDR budget, not additive rates. FDR is requested, not measured here.',
             color=muted, size=10)
    fig.text(.04, .105, 'FFTW / rocFFT: inverse FFT only. Matchedfilter: product + inverse FFT + peak; warm public API.',
             color=muted, size=10)
    fig.text(.04, .06, 'Setup excluded; FFTW PATIENT planning capped at 15 s. GPU filter includes sync, readback and result assembly.',
             color=muted, size=9)
    fig.text(.04, .023, report['date'] + ' · single CPU thread · live measurements on Ryzen AI MAX+ 395 / Radeon 8060S',
             color=muted, size=9)
    out = Path(out)
    fig.savefig(out, facecolor=bg)
    if out.suffix == '.svg':
        out.write_text('\n'.join(line.rstrip() for line in out.read_text().splitlines())+'\n')
    fig.savefig(out.with_suffix('.png'), facecolor=bg, dpi=150)
    plt.close(fig)


def main(argv=None):
    from datetime import date
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', default='docs/assets/teaser.svg')
    args = ap.parse_args(argv)
    report = dict(n=N, data=ND, templates=NT, snr=5.5, date=date.today().isoformat(),
                  cpu=_cpu_name(), gpu=_gpu_name(), fftw_planning_limit_seconds=15,
                  timing='0.5 s warmup, median of >=50 ms blocks; public API', rows=[])
    for device, baseline, fn, measure in [('cpu','FFTW',fftw_ms,cpu_ms),
                                          ('gpu','rocFFT',rocfft_ms,gpu_ms)]:
        for label, kind, fd in [(baseline+'\nFFT only','baseline',None),
                                ('Flat','flat',None)] + [
                                ('Hier.\n'+{.01:'10⁻²', .001:'10⁻³', .0001:'10⁻⁴'}[fd],'hier',fd) for fd in BUDGETS]:
            ms = fn() if kind=='baseline' else measure(kind, fd=fd or .01)
            row = dict(device=device,label=label,kind=kind,fd=fd,ms=ms,
                       timing=dict(_timed.details))
            if device == 'gpu' and kind == 'baseline':
                # Each rocFFT timed call executes eight transforms batches.
                row['timing']['executions_per_call'] = 8
            if row['timing']['max_ms'] > 1.25 * row['timing']['min_ms']:
                print('WARNING: >25% timing spread; check competing workloads', file=sys.stderr)
            if kind=='hier': row.update(_DETAILS[(device,fd)])
            report['rows'].append(row)
            print(json.dumps(row), flush=True)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    plot(report, out)
    print('wrote', out, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
