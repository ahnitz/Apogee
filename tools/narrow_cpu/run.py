#!/usr/bin/env python3
"""Native narrow-coarse study. PYTHONPATH must select the desired fp32 baseline.

Builds measurement-only shared libraries in --build-dir; no package changes.
Every reported time includes product formation, FFT and peak scan. The second
measurement also re-ingests data; templates stay cached, as in a filter bank.
"""
import argparse
import ctypes as C
import json
import hashlib
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

import numpy as np
import matchedfilter as mf
from matchedfilter import _core

MODES = ['q15-radix2', 'q15-radix4', 'q15-swar', 'q15-madd',
         'q15-prequant', 'float-radix4', 'q15-bfp', 'q15-bfp-swar',
         'q15-bfp-madd', 'q15-bfp-prequant']
FLAGS = {'avx': ['-mavx', '-mssse3', '-msse4.1', '-mno-avx2', '-mno-fma', '-DIBITS=128'],
         'avx2': ['-mavx2', '-mfma', '-DIBITS=256'],
         'avx512': ['-mavx512f', '-mavx512bw', '-mavx512dq', '-mavx512vl', '-mfma', '-DIBITS=512']}
TARGET = dict(avx='SSE4', avx2='AVX2', avx512='AVX3')
PEAK = np.dtype([('index', np.int64), ('re', np.float32), ('im', np.float32), ('magnitude', np.float32)], align=True)


def bind(lib, name, args, result=None):
    fn = getattr(lib, name); fn.argtypes = args; fn.restype = result
    return fn


class Candidate:
    def __init__(self, lib, n, nd, nt, mode):
        self.lib, self.n = lib, n
        self.p = lib.narrow_create(n, nd, nt, mode)
        if not self.p: raise RuntimeError('candidate allocation failed')
        self.out = np.empty((nd, nt), np.float32)
    def templates(self, h):
        self.h = np.ascontiguousarray(h, dtype=np.complex64)
        self.lib.narrow_templates(self.p, self.h.ctypes.data)
    def data(self, d):
        self.d = np.ascontiguousarray(d, dtype=np.complex64)
        self.lib.narrow_data(self.p, self.d.ctypes.data)
    def run(self, lo=0, hi=None):
        self.lib.narrow_run(self.p, self.out.ctypes.data, lo, self.n if hi is None else hi)
        return self.out
    def bench(self, reps, ingest):
        return self.lib.narrow_bench(self.p, self.out.ctypes.data, 0, self.n, reps, ingest)
    def close(self):
        if self.p: self.lib.narrow_destroy(self.p); self.p = None


class Reference:
    def __init__(self, bridge, n, nd, nt):
        self.lib, self.bridge = C.CDLL(_core.__file__), bridge
        self.n, self.nd, self.nt = n, nd, nt
        v, i, z = C.c_void_p, C.c_int, C.c_size_t
        bind(self.lib, 'ap_mf_create', [z, i, i], v)
        bind(self.lib, 'ap_mf_destroy', [v])
        for fn in ('ap_mf_set_data', 'ap_mf_set_template'): bind(self.lib, fn, [v, i, v], i)
        bind(self.lib, 'ap_mf_run', [v, i, i, i, i, z, C.c_float, v, v, z, z], i)
        self.p = self.lib.ap_mf_create(n, nd, nt)
        if not self.p: raise RuntimeError('reference allocation failed')
        self.out = np.empty((nd, nt), PEAK)
    def templates(self, h):
        self.h = np.ascontiguousarray(h, dtype=np.complex64)
        for j in range(self.nt):
            assert self.lib.ap_mf_set_template(self.p, j, self.h[j].ctypes.data) == 0
    def data(self, d):
        self.d = np.ascontiguousarray(d, dtype=np.complex64)
        for j in range(self.nd):
            assert self.lib.ap_mf_set_data(self.p, j, self.d[j].ctypes.data) == 0
    def run(self, lo=0, hi=None):
        assert self.lib.ap_mf_run(self.p, 0, self.nd, 0, self.nt, self.n, 0., self.out.ctypes.data,
                                  None, lo, self.n if hi is None else hi) >= 0
        return self.out['magnitude']
    def bench(self, reps, ingest):
        return self.bridge.reference_bench(C.cast(self.lib.ap_mf_run, C.c_void_p),
             C.cast(self.lib.ap_mf_set_data, C.c_void_p), self.p, self.n, self.nd, self.nt,
             self.d.ctypes.data, self.out.ctypes.data, 0, self.n, reps, ingest)
    def close(self):
        if self.p: self.lib.ap_mf_destroy(self.p); self.p = None


def build(isa, directory):
    path = directory / (isa+'.so')
    subprocess.run(['g++', '-O3', '-std=c++17', '-fPIC', '-shared', '-fno-math-errno',
                    *FLAGS[isa], str(Path(__file__).with_name('kernels.cpp')), '-o', str(path)], check=True)
    lib = C.CDLL(str(path)); v, i = C.c_void_p, C.c_int
    bind(lib, 'narrow_create', [i]*4, v)
    bind(lib, 'narrow_destroy', [v])
    for fn in ('narrow_templates', 'narrow_data'): bind(lib, fn, [v, v])
    bind(lib, 'narrow_run', [v, v, i, i])
    bind(lib, 'narrow_bench', [v, v, i, i, i, i], C.c_double)
    bind(lib, 'reference_bench', [v, v, v, i, i, i, v, v, i, i, i, i], C.c_double)
    return lib


def noise(rng, shape):
    return (rng.normal(size=shape)+1j*rng.normal(size=shape)).astype(np.complex64)


def correctness(lib):
    """Independent float control, SWAR equivalence, tails, windows and stress."""
    summary = []
    for n in (64, 128, 256, 512, 1024):
        rng = np.random.default_rng(n)
        h, d = noise(rng, (37, n)), noise(rng, (3, n))
        for scenario in ('noise', 'coherent', 'cancellation', 'zero', 'scale'):
            if scenario == 'coherent': h[:]=1; d[:]=1
            if scenario == 'cancellation':
                h[:]=1; d[:]=np.where(np.arange(n)%2, -1, 1)
            if scenario == 'zero': d[:]=0
            if scenario == 'scale': h=noise(rng,(37,n))*1e-6; d=noise(rng,(3,n))*1e6
            plans = [Reference(lib,n,3,37)] + [Candidate(lib,n,3,37,j) for j in range(10)]
            try:
                for p in plans: p.templates(h); p.data(d)
                for lo, hi in ((0,n), (n//4,3*n//4)):
                    y=[p.run(lo,hi).copy() for p in plans]
                    np.testing.assert_allclose(y[6],y[0],rtol=3e-6,atol=3e-5)
                    np.testing.assert_array_equal(y[2],y[3])
                    np.testing.assert_array_equal(y[7],y[8])
                    for z in y: assert np.isfinite(z).all() and (z>=0).all()
                    # Quantized transforms have an absolute-error floor. Check
                    # zero-valued windows against the global reference scale.
                    scale=max(float(y[0].max()),1.)
                    for j,z in enumerate(y[1:]):
                        if scenario in ('coherent','cancellation','zero'):
                            assert np.max(abs(z-y[0])) < .005*scale, (n,scenario,MODES[j])
            finally:
                for p in plans:p.close()
        summary.append(n)
    return summary


def timing(lib, n, nt, rounds):
    rng=np.random.default_rng(n+nt);d=noise(rng,(8,n));h=noise(rng,(nt,n))
    plans=[Reference(lib,n,8,nt)]+[Candidate(lib,n,8,nt,j) for j in range(10)]
    rows=[]
    try:
        for p in plans:p.templates(h);p.data(d);p.run()
        truth=plans[0].run().copy()
        for ingest in (0,1):
            times=[[] for p in plans]
            reps=max(3,min(1000,int(.010/max(plans[0].bench(3,ingest),1e-7))))
            for r in range(rounds):
                # Pair every candidate with the reference, reversing order on
                # alternate rounds, rather than timing all float then all Q15.
                for j in (range(1,11) if r%2==0 else range(10,0,-1)):
                    a,b=(0,j) if r%2==0 else (j,0)
                    ta=plans[a].bench(reps,ingest);tb=plans[b].bench(reps,ingest)
                    times[j].append([ta,tb] if a==0 else [tb,ta])
            for j in range(1,11):
                sample=times[j]
                rows.append(dict(mode=MODES[j-1],band=n,templates=nt,data_rows=8,ingest=bool(ingest),
                                 speedup=statistics.median(a/b for a,b in sample),samples=sample,
                                 max_relative_error=float(np.max(abs(plans[j].run()/truth-1)))))
    finally:
        for p in plans:p.close()
    return rows


def rate_compare(ref, other):
    rows={}
    for fd in (.01,.001):
        ordered=np.sort(ref);count=round(fd*len(ref));thr=(float(ordered[count-1])+float(ordered[count]))/2
        a,b=ref<thr,other<thr;dis=int(np.count_nonzero(a!=b));budget=max(1,int(np.ceil(.125*count)))
        rows[str(fd)]=dict(threshold=thr,reference_dismissed=int(a.sum()),candidate_dismissed=int(b.sum()),
                          paired_disagreements=dis,budget=budget,passes=dis<=budget)
    rows['max_relative_error']=float(np.max(abs(other/ref-1)))
    return rows


def fdr(lib, n, trials):
    batch=512;nt=4;rng=np.random.default_rng(91027+n);k=np.arange(n)
    power=np.exp(-k[None,:]/(n/np.array([2.,4.,6.,8.])[:,None]));power/=power.sum(axis=1,keepdims=True)
    h=(np.sqrt(power)*np.exp(1j*rng.uniform(-np.pi,np.pi,(nt,n)))).astype(np.complex64)
    plans=[Reference(lib,n,batch,nt)]+[Candidate(lib,n,batch,nt,j) for j in range(10)]
    matched=np.arange(batch)%4;ys=[[] for p in plans]
    try:
        for p in plans:p.templates(h)
        for _ in range(trials//batch):
            lag=rng.integers(0,8*n,batch)/8
            signal=h[matched]*np.exp(-2j*np.pi*lag[:,None]*k/n)
            data=(noise(rng,(batch,n))+5.5*signal).astype(np.complex64)
            keep=np.abs(np.sum(data.astype(np.complex128)*np.conj(signal),axis=1))>=5.5
            for j,p in enumerate(plans):
                p.data(data);ys[j].append(p.run()[np.arange(batch),matched][keep].copy())
        y=[np.concatenate(v) for v in ys]
        np.testing.assert_array_equal(y[2],y[3]);np.testing.assert_array_equal(y[7],y[8])
        return dict(band=n,detected=len(y[0]),trials=trials,
                    modes={name:rate_compare(y[0],z) for name,z in zip(MODES,y[1:])},
                    negative_control=rate_compare(y[0],y[0]*.996),
                    strong_negative_control=rate_compare(y[0],y[0]*.98))
    finally:
        for p in plans:p.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir',type=Path,default=Path('/tmp/mf-narrow-cpu'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--isas',nargs='+',choices=FLAGS,default=list(FLAGS))
    parser.add_argument('--bands',type=int,nargs='+',default=[256,512,1024])
    parser.add_argument('--templates',type=int,nargs='+',default=[32,128])
    parser.add_argument('--rounds',type=int,default=7)
    parser.add_argument('--fdr',action='store_true',help='32768 paired trials per band, on AVX2')
    args=parser.parse_args();args.build_dir.mkdir(parents=True,exist_ok=True)
    if args.rounds<1:parser.error('rounds must be positive')
    supported=_core.targets();result=dict(platform=platform.platform(),baseline=_core.__file__,baseline_sha256=hashlib.sha256(Path(_core.__file__).read_bytes()).hexdigest(),
        compiler=subprocess.check_output(['g++','--version'],text=True).splitlines()[0],
        affinity=sorted(os.sched_getaffinity(0)) if hasattr(os,'sched_getaffinity') else None,timings=[],accuracy={},fdr=[])
    def save():args.output.write_text(json.dumps(result,indent=2)+'\n')
    for isa in args.isas:
        if TARGET[isa] not in supported:raise RuntimeError(f'{isa} not supported on this machine')
        _core.set_target(None);_core.set_target(TARGET[isa]);lib=build(isa,args.build_dir)
        result['accuracy'][isa]=correctness(lib);print(isa,'correctness passed',flush=True)
        for n in args.bands:
            for nt in args.templates:
                rows=timing(lib,n,nt,args.rounds)
                for row in rows:row['isa']=isa
                result['timings'].extend(rows);save()
                print(isa,n,nt,[(r['mode'],round(r['speedup'],3)) for r in rows if not r['ingest']],flush=True)
        if args.fdr and isa=='avx2':
            for n in args.bands:
                result['fdr'].append(fdr(lib,n,32768));save();print('FDR',n,'done',flush=True)
    _core.set_target(None);save()


if __name__=='__main__':main()
