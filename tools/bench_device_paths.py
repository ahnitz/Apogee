#!/usr/bin/env python3
"""Compare warm CPU/GPU flat and calibrated hierarchical execution.

Same data, templates, batch shape and window on both devices. No reference FFT
timings. File calibration is required; uncovered hierarchical cases are reported.
"""
import argparse
import gc
import json
import time
import numpy as np
import matchedfilter as mf
from matchedfilter.benchmark import _inspiral_power


def measure(n, nd, nt, rounds=9):
    rng = np.random.default_rng(840+n)
    ref = _inspiral_power(n)
    h = (np.sqrt(ref)*np.exp(1j*rng.uniform(0,2*np.pi,(nt,n)))).astype(np.complex64)
    h /= np.linalg.norm(h,axis=1)[:,None]
    d = (rng.normal(size=(nd,n))+1j*rng.normal(size=(nd,n))).astype(np.complex64)
    window = (int(.2*n)&~15, int(.8*n)&~15)
    plans, result = {}, {'n':n,'data':nd,'templates':nt,'paths':{}}
    flat_outputs = {}
    for device in ('cpu','gpu:0'):
        for kind in ('flat','hier'):
            key = device.split(':')[0]+'_'+kind
            f = None
            try:
                if kind == 'flat':
                    f = mf.MatchedFilter(n,nd,nt,device=device)
                else:
                    f = mf.HierarchicalFilter(n,nd,nt,snr=5.5,fd=.001,device=device)
                    f.set_reference(ref)
                f.set_templates(h)
                f.set_data(d)
                out = f.run(binsize=n,threshold=0.,window=window).copy()
                if kind == 'flat':
                    flat_outputs[device] = out
                else:
                    flat = flat_outputs[device]
                    live = out['index'] >= 0
                    np.testing.assert_array_equal(out['index'][live],flat['index'][live])
                    np.testing.assert_allclose(out['value'][live],flat['value'][live],rtol=2e-5,atol=2e-5)
                plans[key] = f
                result['paths'][key] = {'device':str(f.device)}
                if kind == 'hier': result['paths'][key]['band'] = f.config[0]
            except ValueError as error:
                result['paths'][key] = {'unavailable':str(error)}
                if f is not None: del f
    if len(flat_outputs) == 2:
        a,b = flat_outputs['cpu'],flat_outputs['gpu:0']
        np.testing.assert_array_equal(a['index'],b['index'])
        np.testing.assert_allclose(a['value'],b['value'],rtol=2e-5,atol=2e-5)
    samples, repeats = {}, {}
    for key,f in plans.items():
        for _ in range(3): f.run(binsize=n,threshold=5.5,window=window)
        begin=time.perf_counter()
        f.run(binsize=n,threshold=5.5,window=window)
        elapsed=time.perf_counter()-begin
        repeats[key] = max(1,min(50,int(.05/max(elapsed,1e-9))))
        samples[key]=[]
    keys=list(plans)
    for round_index in range(rounds):
        for key in (keys if round_index%2 == 0 else keys[::-1]):
            f=plans[key]
            begin=time.perf_counter()
            for _ in range(repeats[key]): f.run(binsize=n,threshold=5.5,window=window)
            samples[key].append((time.perf_counter()-begin)/repeats[key])
    for key,values in samples.items():
        median=float(np.median(values))
        result['paths'][key].update(ms_per_batch=median*1000,
            us_per_pair=median*1e6/(nd*nt),min_ms=min(values)*1000,max_ms=max(values)*1000)
        if key.endswith('hier'): result['paths'][key]['refine_rate']=plans[key].refine_rate
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n',type=int,nargs='+',default=[1024,2048,4096,8192,16384,32768,65536])
    parser.add_argument('--data',type=int,default=16)
    parser.add_argument('--templates',type=int,default=64)
    parser.add_argument('--rounds',type=int,default=9)
    parser.add_argument('--json',required=True)
    args=parser.parse_args()
    if min(args.data,args.templates,args.rounds)<1: parser.error('batch dimensions and rounds must be positive')
    report={'backend':mf.backend(),'devices':[str(d) for d in mf.devices()],
            'method':'warm run(), pure Gaussian noise, inspiral-shaped normalized templates, 60% window, one bin, threshold 5.5; hierarchical snr=5.5 fd=.001 from files',
            'rounds':args.rounds,'results':[]}
    for n in args.n:
        row=measure(n,args.data,args.templates,args.rounds)
        report['results'].append(row)
        print(json.dumps(row),flush=True)
        with open(args.json,'w') as stream: json.dump(report,stream,indent=2)
        gc.collect()


if __name__ == '__main__': main()
