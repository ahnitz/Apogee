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
from matchedfilter.benchmark import _inspiral_power, SUPPORTED_LENGTHS


def check_flat_peaks(a, b, data, templates, window):
    """Accept float32 peak ties only after checking both lags independently."""
    np.testing.assert_array_equal(a['index'] >= 0, b['index'] >= 0)
    same = a['index'] == b['index']
    np.testing.assert_allclose(a['value'][same], b['value'][same], rtol=2e-5, atol=2e-5)
    for di, ti, bi in np.argwhere(~same):
        rho = np.fft.ifft(data[di].astype(np.complex128) *
                          np.conj(templates[ti].astype(np.complex128))) * data.shape[1]
        maximum = np.abs(rho[window[0]:window[1]]).max()
        for peaks in (a, b):
            lag = int(peaks['index'][di, ti, bi])
            assert window[0] <= lag < window[1]
            np.testing.assert_allclose(peaks['value'][di, ti, bi], rho[lag], rtol=2e-5, atol=2e-5)
            np.testing.assert_allclose(abs(rho[lag]), maximum, rtol=2e-5, atol=2e-5)


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
            except (ValueError, mf.UnsupportedSize) as error:
                result['paths'][key] = {'unavailable':str(error)}
                if f is not None: del f
    if len(flat_outputs) == 2:
        a,b = flat_outputs['cpu'],flat_outputs['gpu:0']
        check_flat_peaks(a, b, d, h, window)
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


def default_shape(n, budget=64 << 20):
    """128 x 512 where it fits; halve both axes to bound input storage."""
    nd, nt = 128, 512
    while (nd + nt) * n * 8 > budget and nd > 1:
        nd //= 2
        nt //= 2
    return nd, nt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n',type=int,nargs='+',default=SUPPORTED_LENGTHS)
    parser.add_argument('--data',type=int,default=0, help='0 selects a memory-bounded batch per size')
    parser.add_argument('--templates',type=int,default=0, help='set with --data for a fixed batch')
    parser.add_argument('--rounds',type=int,default=9)
    parser.add_argument('--json',required=True)
    args=parser.parse_args()
    if args.rounds < 1 or args.data < 0 or args.templates < 0 or bool(args.data) != bool(args.templates):
        parser.error('rounds must be positive; provide both positive batch dimensions or neither')
    report={'backend':mf.backend(),'devices':[str(d) for d in mf.devices()],
            'method':'warm run(), pure Gaussian noise, inspiral-shaped normalized templates, 60% window, one bin, threshold 5.5; hierarchical snr=5.5 fd=.001 from files',
            'rounds':args.rounds,'results':[]}
    for n in args.n:
        nd, nt = (args.data, args.templates) if args.data else default_shape(n)
        row=measure(n,nd,nt,args.rounds)
        report['results'].append(row)
        print(json.dumps(row),flush=True)
        with open(args.json,'w') as stream: json.dump(report,stream,indent=2)
        gc.collect()


if __name__ == '__main__': main()
