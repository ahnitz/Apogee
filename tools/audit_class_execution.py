#!/usr/bin/env python3
"""Measure class/series scheduling without changing filtering kernels.

Run against an isolated package snapshot via PYTHONPATH. Explicit coarse
parameters isolate scheduling from calibration selection; these are not FDR
measurements. All timings are warm public calls unless labelled otherwise.
"""
import argparse
import contextlib
import gc
import hashlib
import inspect
import textwrap
import types
import json
import os
import platform
import time
from pathlib import Path

import numpy as np
import matchedfilter as mf


@contextlib.contextmanager
def environment(**values):
    old = {k: os.environ.get(k) for k in values}
    try:
        os.environ.update({k: str(v) for k, v in values.items()})
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def times(calls, rounds=7):
    samples = {k: [] for k in calls}
    repeats = {}
    for k, fn in calls.items():
        fn(); fn()
        begin = time.perf_counter(); fn()
        repeats[k] = max(1, min(25, int(.025 / max(time.perf_counter()-begin, 1e-9))))
    for r in range(rounds):
        keys = list(calls)
        if r % 2:
            keys.reverse()
        for k in keys:
            begin = time.perf_counter()
            for _ in range(repeats[k]):
                calls[k]()
            samples[k].append((time.perf_counter()-begin)*1000/repeats[k])
    return {k: {'median_ms': float(np.median(v)), 'min_ms': min(v), 'max_ms': max(v),
                'samples_ms': v} for k, v in samples.items()}


def inputs(n, blocks, nt, groups=1):
    rng = np.random.default_rng(34567+n+nt)
    # FFT(series)/n has unit component variance, as spectral noise does.
    series = ((rng.normal(size=(blocks+1)*n//2) +
               1j*rng.normal(size=(blocks+1)*n//2))*np.sqrt(n)).astype(np.complex64)
    power = np.exp(-np.arange(n)/64.)
    power /= power.sum()
    h = (np.sqrt(power)[None, :] * np.exp(1j*rng.uniform(0, 2*np.pi, (nt, n)))).astype(np.complex64)
    starts = np.arange(blocks, dtype=np.uintp)*(n//2)
    lo = np.full(blocks, n//4, dtype=np.uintp)+np.arange(blocks, dtype=np.uintp)%groups
    hi = lo+n//2
    return series, starts, lo, hi, h


def plan(n, nd, nt, device, kind, h, group=8):
    with environment(MF_DGROUP=group):
        if kind == 'hier':
            f = mf.HierarchicalFilter(n, nd, nt, device=device, band=256)
            f.set_coarse_threshold(4.)
        else:
            f = mf.MatchedFilter(n, nd, nt, device=device)
    f.set_templates(h)
    return f


def validate(a, b):
    np.testing.assert_array_equal(a['index'], b['index'])
    np.testing.assert_allclose(a['value'], b['value'], rtol=3e-5, atol=3e-5)


def batching(device, rounds):
    rows = []
    for n in (1024, 4096, 16384):
        ser, st, lo, hi, h = inputs(n, 128, 512)
        for kind in ('flat', 'hier'):
            configs = [('nd1', 1, 8), ('nd8', 8, 8), ('nd32', 32, 8)]
            if device == 'cpu' and kind == 'hier':
                configs += [('group32', 32, 32)]
            plans = {label: plan(n, nd, 512, device, kind, h, group)
                     for label, nd, group in configs}
            calls = {label: (lambda f=f: f.run_series(ser, st, lo, hi, threshold=5.5))
                     for label, f in plans.items()}
            reference = calls['nd1']().copy()
            for fn in calls.values(): validate(reference, fn())
            measured = times(calls, rounds)
            row = dict(suite='batching', device=device, kind=kind, n=n, blocks=128,
                       templates=512, results=measured)
            if kind == 'hier': row['refine_rate'] = plans['nd1'].refine_rate
            rows.append(row); print(json.dumps(row), flush=True)
            del plans, calls; gc.collect()
    return rows


def layout(device, rounds):
    rows = []
    for n, blocks, nt, groups in ((64,4096,1,1), (1024,128,32,1),
                                  (1024,128,32,2), (1024,128,32,16),
                                  (1024,128,32,128), (4096,128,512,1)):
        ser, st, lo, hi, h = inputs(n, blocks, nt, groups)
        f = plan(n, 32, nt, device, 'flat', h)
        args = (ser,st,lo,hi)
        calls = {'structured': lambda:f.run_series(*args),
                 'raw':lambda:f.run_series(*args,raw=True),
                 'validation_only':lambda:f._series_layout(*args,None,None)}
        row = dict(suite='layout',device=device,n=n,blocks=blocks,templates=nt,
                   window_groups=groups,results=times(calls,rounds))
        # A bound on the gain from an explicit immutable prepared-layout API.
        validated = f._series_layout(*args,None,None)
        original = f._series_layout
        f._series_layout = lambda *unused: validated
        row['prevalidated'] = times({'structured':lambda:f.run_series(*args)},rounds)
        f._series_layout = original
        if device == 'gpu':
            shared = f.empty_shared(ser.shape); shared[:] = ser
            row['shared_source'] = times({'structured':lambda:f.run_series(shared,st,lo,hi)},rounds)
        rows.append(row); print(json.dumps(row),flush=True)
        del f; gc.collect()
    return rows


def cache(rounds):
    """Threshold/window recordings and ordinary versus shared bank residency."""
    rows=[]
    from matchedfilter import _vkcompute as vk
    for shared in (False,True):
        n, nd, nt = 4096,128,512
        ser,st,lo,hi,h = inputs(n,nd,nt,2)
        f=plan(n,nd,nt,'gpu','flat',h)
        if shared:
            bank=f.empty_shared(h.shape);bank[:]=h;f.set_templates(bank)
        counts={'writes':0,'write_bytes':0,'submits':0}
        write=vk._Buffer.write;submit=f._gpu._submit
        def counted_write(buf,array):
            counts['writes']+=1;counts['write_bytes']+=array.nbytes
            return write(buf,array)
        def counted_submit(cmd):
            if cmd is not None or getattr(f._gpu,'_pending_forward',None) is not None:
                counts['submits']+=1
            return submit(cmd)
        vk._Buffer.write=counted_write;f._gpu._submit=counted_submit
        try:
            f.run_series(ser,st,lo,hi)
            cold=dict(counts)
            for k in counts:counts[k]=0
            f.run_series(ser,st,lo,hi)
            warm=dict(counts)
        finally:
            vk._Buffer.write=write;f._gpu._submit=submit
        row=dict(suite='cache',shared_templates=shared,n=n,blocks=nd,templates=nt,
                 cold=cold,warm=warm)
        row['results']=times({'two_windows':lambda:f.run_series(ser,st,lo,hi)},rounds)
        # Force whole-cache eviction with more distinct threshold recordings
        # than the default entry limit. Same inputs, no setter calls.
        thresholds=np.arange(40)/10
        def sweep():
            for threshold in thresholds:
                f.run_series(ser,st,lo,hi,threshold=float(threshold))
        row['threshold_sweep_40']=times({'sweep':sweep},3)
        rows.append(row);print(json.dumps(row),flush=True)
        del f;gc.collect()
    return rows


def cache_limits(rounds):
    n, blocks, nt = 1024, 128, 32
    ser, st, lo, hi, h = inputs(n, blocks, nt, 128)
    plans = {k: plan(n,32,nt,'gpu','flat',h) for k in ('entries32','entries256')}
    plans['entries256']._gpu.cache_limit_entries = 256
    calls = {k: (lambda f=f:f.run_series(ser,st,lo,hi)) for k,f in plans.items()}
    validate(calls['entries32']().copy(),calls['entries256']())
    result = dict(suite='cache_limits',n=n,blocks=blocks,templates=nt,window_groups=128,
                  results=times(calls,rounds))
    accounting={}
    for label,f in plans.items():
        buffers=[b for batch in f._gpu._batches.values() for b in batch[:-1]]
        buffers += [b for batch in getattr(f._gpu,'_forwards',{}).values() for b in batch[:-1]]
        unique={int(b.ptr.value if hasattr(b.ptr,'value') else b.ptr):b.nbytes for b in buffers}
        accounting[label]={'counted_bytes':sum(b.nbytes for b in buffers),
                           'unique_allocation_bytes':sum(unique.values()),
                           'dispatch_entries':len(f._gpu._batches)}
    result['memory_accounting']=accounting
    print(json.dumps(result),flush=True)
    return [result]


def caller_chunks(device, rounds):
    n, blocks, nt = 4096, 128, 512
    ser, st, lo, hi, h = inputs(n,blocks,nt)
    f=plan(n,32,nt,device,'flat',h)
    def templates():
        return [f.run_series(ser,st,lo,hi,templates=(t,64)) for t in range(0,nt,64)]
    def blocks_separately():
        return [f.run_series(ser,st[b:b+1],lo[b:b+1],hi[b:b+1]) for b in range(blocks)]
    full=f.run_series(ser,st,lo,hi).copy()
    validate(full,np.concatenate(templates(),axis=1))
    validate(full,np.concatenate(blocks_separately(),axis=0))
    result=dict(suite='caller_chunks',device=device,n=n,blocks=blocks,templates=nt,
                results=times({'one_call':lambda:f.run_series(ser,st,lo,hi),
                               'eight_template_calls':templates,
                               '128_block_calls':blocks_separately},rounds))
    print(json.dumps(result),flush=True)
    return [result]


def vector_validation(device, rounds):
    # Prototype only: replace the Python-per-window loop while retaining all
    # other public checks. This is not an unchecked prepared-layout shortcut.
    source=textwrap.dedent(inspect.getsource(mf.MatchedFilter._series_layout))
    old="nbset = {self.nbins(binsize, (int(a), int(b))) for a, b in zip(ws, we)}"
    new="""low = np.minimum(ws, self.n)
    high = np.minimum(we, self.n)
    if np.any(low >= high):
        raise ValueError('every block must have a nonempty search window')
    nbset = set(map(int, np.unique(1 + (high-low-1)//binsize)))"""
    assert old in source, 'update prototype for this package version'
    namespace={}
    exec(source.replace(old,new),vars(mf),namespace)
    prototype=namespace['_series_layout']
    rows=[]
    for n,blocks,nt in ((64,4096,1),(1024,128,32),(4096,128,512)):
        ser,st,lo,hi,h=inputs(n,blocks,nt)
        f=plan(n,32,nt,device,'flat',h)
        baseline=f._series_layout
        alternate=types.MethodType(prototype,f)
        def call(method):
            f._series_layout=method
            return f.run_series(ser,st,lo,hi)
        validate(call(baseline).copy(),call(alternate))
        row=dict(suite='vector_validation',device=device,n=n,blocks=blocks,templates=nt,
                 results=times({'baseline':lambda:call(baseline),
                                'vectorized':lambda:call(alternate)},rounds))
        rows.append(row);print(json.dumps(row),flush=True)
    return rows


def reorder_cpu(rounds):
    rows=[]
    for kind in ('flat','hier'):
        n,blocks,nt=1024,128,512
        ser,st,lo,hi,h=inputs(n,blocks,nt,2)
        f=plan(n,32,nt,'cpu',kind,h)
        def grouped():
            # Include planning and scatter in this candidate's timed work.
            order=np.lexsort((hi,lo))
            inverse=np.argsort(order)
            return f.run_series(ser,st[order],lo[order],hi[order])[inverse]
        baseline=lambda:f.run_series(ser,st,lo,hi)
        validate(baseline().copy(),grouped())
        row=dict(suite='reorder_cpu',kind=kind,n=n,blocks=blocks,templates=nt,
                 window_groups=2,results=times({'adjacent_only':baseline,
                                               'group_and_scatter':grouped},rounds))
        rows.append(row);print(json.dumps(row),flush=True)
    return rows


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--device',choices=['cpu','gpu'],default='cpu')
    ap.add_argument('--suite',choices=['batching','layout','cache','cache_limits','caller_chunks','vector_validation','reorder_cpu'],required=True)
    ap.add_argument('--rounds',type=int,default=7)
    ap.add_argument('--json',required=True)
    a=ap.parse_args()
    if a.rounds < 1:
        ap.error('--rounds must be positive')
    result={'host':platform.node(),'python':platform.python_version(),'numpy':np.__version__,
            'package':mf.__file__,'backend':mf.backend(),'suite':a.suite,
            'method':'warm calls; alternating variant order; median and range; explicit band=256/gate=4 for hierarchical'}
    package=Path(mf.__file__).parent
    revision=package.parent.parent/'revision.txt'
    result['snapshot_revision']=revision.read_text().strip() if revision.exists() else None
    result['core_sha256']=hashlib.sha256(Path(mf._core.__file__).read_bytes()).hexdigest()
    result['manifest_sha256']=hashlib.sha256((package/'spirv/manifest.json').read_bytes()).hexdigest()
    result['rows']=(globals()[a.suite](a.rounds) if a.suite in ('cache','cache_limits','reorder_cpu')
                    else globals()[a.suite](a.device,a.rounds))
    Path(a.json).write_text(json.dumps(result,indent=2)+'\n')


if __name__=='__main__':main()
