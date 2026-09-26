#!/usr/bin/env python3
"""Compare public class calls with identical native binaries in two packages.

Use frozen package directories, not live builds, while kernel work is ongoing.
Example: LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/bench_class_changes.py \
  --baseline /tmp/base/python/matchedfilter --candidate /tmp/new/python/matchedfilter \
  --output /tmp/class-comparison.json
"""
import argparse
import hashlib
import importlib.util
import json
import platform
import time
from pathlib import Path
import numpy as np


def load(name, path):
    import sys
    spec = importlib.util.spec_from_file_location(name, path/'__init__.py',
                                                 submodule_search_locations=[str(path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def measure(calls, rounds):
    samples = {k:[] for k in calls}
    repeats = {}
    for key, fn in calls.items():
        fn(); fn()
        begin = time.perf_counter(); fn()
        repeats[key] = max(1, min(40, int(.02/max(time.perf_counter()-begin, 1e-9))))
    for r in range(rounds):
        for key in list(calls)[::1 if r%2 == 0 else -1]:
            begin = time.perf_counter()
            for _ in range(repeats[key]):
                calls[key]()
            samples[key].append((time.perf_counter()-begin)*1000/repeats[key])
    return {k:dict(median_ms=float(np.median(v)), samples_ms=v) for k,v in samples.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=7)
    parser.add_argument('--device', choices=['cpu','gpu'], action='append')
    parser.add_argument('--kind', choices=['flat','hier'], action='append')
    parser.add_argument('--candidate-only', action='store_true', help='time the candidate alone; useful for baseline crash reproductions')
    parser.add_argument('--case', action='append', help='n,blocks,templates,windows,binsize; repeatable')
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    modules = {k:load('_mf_'+k, p) for k,p in [('baseline',args.baseline),('candidate',args.candidate)]}
    if args.candidate_only:
        modules.pop('baseline')
    cores = {k:hashlib.sha256(next(p.glob('_core*.so')).read_bytes()).hexdigest()
             for k,p in [('baseline',args.baseline),('candidate',args.candidate)]}
    shaders = {k:hashlib.sha256((p/'spirv/manifest.json').read_bytes()).hexdigest()
               for k,p in [('baseline',args.baseline),('candidate',args.candidate)]}
    if len(set(shaders.values())) != 1:
        raise ValueError('shader manifests differ; cannot isolate class changes')
    if len(set(cores.values())) != 1:
        raise ValueError('native binaries differ; cannot isolate class changes')
    result = dict(machine=platform.platform(), cpu_backend=modules['candidate'].backend(),
                  devices=[str(d) for d in modules['candidate'].devices()],
                  native_sha256=cores, shader_manifest_sha256=shaders, coarse_threshold=4.0,
                  cpu_comparison='shared native plan; separate Python wrappers',
                  rows=[])
    # One call covers all blocks; ndata=blocks keeps run/series shapes comparable.
    cases = [(1024,1,1,1,1024), (64,4096,1,1,64),
             (1024,128,32,1,1024), (1024,128,512,1,1024), (1024,128,512,2,1024),
             (1024,128,32,128,1024), (4096,128,512,1,4096),
             (16384,128,512,1,16384), (1024,16,16,1,1)]
    if args.case:
        cases = [tuple(map(int, case.split(','))) for case in args.case]
        if any(len(case)!=5 or min(case)<1 for case in cases):
            parser.error('--case needs five positive integers')
    for device in args.device or ['cpu','gpu']:
      for kind in args.kind or ['flat','hier']:
       for n,blocks,nt,groups,binsize in cases:
        if kind=='hier' and n<1024:
            continue
        rng=np.random.default_rng(541+n)
        series=((rng.normal(size=(blocks+1)*n//2)+1j*rng.normal(size=(blocks+1)*n//2))*np.sqrt(n)).astype('complex64')
        power=np.exp(-np.arange(n)/64.); power/=power.sum()
        h=(np.sqrt(power)[None,:]*np.exp(1j*rng.uniform(0,2*np.pi,(nt,n)))).astype('complex64')
        starts=np.arange(blocks,dtype=np.uintp)*(n//2)
        lo=np.full(blocks,n//4,dtype=np.uintp)+np.arange(blocks,dtype=np.uintp)%groups
        hi=lo+n//2
        data=np.zeros((blocks,n), dtype='complex64')
        for i,start in enumerate(starts):
            block=series[int(start):int(start)+n]
            data[i,:len(block)]=block
        data=(np.fft.fft(data,axis=-1)/n).astype('complex64')
        plans={}
        try:
          for key,mf in modules.items():
            cls=mf.MatchedFilter if kind=='flat' else mf.HierarchicalFilter
            f=cls(n,blocks,nt,device=device,**({'band':256} if kind=='hier' else {}))
            if kind=='hier': f.set_coarse_threshold(4.)
            f.set_templates(h); plans[key]=f
          if device == 'cpu' and 'baseline' in plans:
            # Use exactly the same native plan/allocation for both wrappers.
            # Distinct native buffer addresses can change cache conflicts;
            # those differences are unrelated to the Python class changes.
            for f in plans.values(): f._execution_plan()
            plans['candidate']._mf = plans['baseline']._mf
          calls={k:(lambda f=f:f.run_series(series,starts,lo,hi,binsize=binsize)) for k,f in plans.items()}
          values = [fn().copy() for fn in calls.values()]
          if len(values) == 2:
              a, b = values
              np.testing.assert_array_equal(a['index'],b['index'])
              np.testing.assert_allclose(a['value'],b['value'],atol=3e-5,rtol=3e-5)
          row=dict(device=device,kind=kind,n=n,blocks=blocks,templates=nt,windows=groups,binsize=binsize,
                   series=measure(calls,args.rounds))
          if kind=='hier':
            row['refinement_fraction'] = {k:f.stats[1]/f.stats[0] for k,f in plans.items()}
          if groups==1:
            for f in plans.values(): f.set_data(data)
            row['run']=measure({k:(lambda f=f:f.run(binsize=binsize,window=(int(lo[0]),int(hi[0])))) for k,f in plans.items()},args.rounds)
          if n==4096:
            row['template_chunks']=measure({k:(lambda f=f:[f.run_series(series,starts,lo,hi,templates=(t,64)) for t in range(0,nt,64)]) for k,f in plans.items()},args.rounds)
          if n==1024 and groups==1 and blocks==128:
            row['bank_update']=measure({k:(lambda f=f:(f.set_templates(h),f.run_series(series,starts,lo,hi))) for k,f in plans.items()},args.rounds)
          result['rows'].append(row)
          print(device,kind,n,blocks,nt,groups, 'series ms',*[round(row['series'][k]['median_ms'],4) for k in modules],flush=True)
          args.output.parent.mkdir(parents=True,exist_ok=True)
          args.output.write_text(json.dumps(result,indent=2)+'\n')
        finally:
          for f in plans.values():
            if f._gpu is not None: f._gpu.destroy()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
