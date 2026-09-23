#!/usr/bin/env python3
"""Score the tuner's pick against the measured best of every admissible family."""
import numpy as np, time, matchedfilter as mf
from matchedfilter.benchmark import _inspiral_power
fd=1e-3
def score(n,snr,nd=8,nt=32):
    p=_inspiral_power(n); t=mf._load_tuning(); floor=mf._dismissal_floor(t)
    use,_=mf._snr_rows_for(snr,t["snrs_at"][n])
    pick=mf.choose_config(p,n,snr,fd)
    rng=np.random.default_rng(7); amp=np.sqrt(p)
    h=(amp*np.exp(1j*rng.uniform(0,2*np.pi,(nt,n)))).astype(np.complex64)
    h/=np.sqrt((np.abs(h)**2).sum(axis=1,keepdims=True))
    d=(rng.standard_normal((nd,n))+1j*rng.standard_normal((nd,n))).astype(np.complex64)
    ws=int(0.2*n)&~15; we=ws+(int(0.6*n)&~15); bs=min(2048,we-ws)
    flat=mf.MatchedFilter(n,nd,nt); flat.set_data(d); flat.set_templates(h)
    def per(fn,fl=0.05):
        fn(); k=1
        while True:
            t0=time.perf_counter()
            for _ in range(k): fn()
            dt=time.perf_counter()-t0
            if dt>=fl: return dt/k
            k*=2
    fam={}
    for s_ in set(list(use)+[snr]):
        for r in t["by_ns"].get((n,round(s_,2)),()):
            if r[1]>=n: continue
            fam.setdefault((r[1],r[2],r[3]),{}).setdefault(r[7],[]).append((r[5],r[6],r[8]))
    res=[]
    for (band,U,K),bym in fam.items():
        f,be=mf._band_features(p,band); dc=[]
        for mg,rows in bym.items():
            fq=min(f,max(r[0] for r in rows)); bq=min(be,max(r[1] for r in rows))
            cov=[dm for (tf,tbe,dm) in rows if tf>=fq-1e-9 and tbe>=bq-1e-9]
            if cov: dc.append((mg,max(cov)))
        if not dc: continue
        m=mf._margin_at_budget(dc,fd,floor)
        if m is None: continue
        hf=mf.HierarchicalFilter(n,nd,nt,snr,fd,band=band,oversample=U,taps=K)
        hf.set_reference(p); hf._mf.set_coarse_margin(float(m)); hf.set_data(d); hf.set_templates(h)
        r=[per(lambda: flat.run(binsize=bs,threshold=snr,window=(ws,we)))/
           per(lambda: hf.run(binsize=bs,threshold=snr,window=(ws,we))) for _ in range(3)]
        res.append((float(np.median(r)),(band,U,K)))
    res.sort(reverse=True)
    mine=[x for x in res if x[1]==pick[:3]]
    return (mine[0][0] if mine else 0), res[0][0], pick, res[0][1]
print("  %-6s %-6s %-20s %-20s %s"%("n","snr","picked","best measured","score"))
for n,snr in ((4096,5.5),(4096,6.0),(4096,6.5),(8192,5.5),(16384,6.0)):
    got,best,pick,bc=score(n,snr)
    print("  %-6d %-6.1f %-20s %-20s %.0f%%"%(n,snr,"%d/%d/%d m%.3f"%pick,
          "%d/%d/%d"%bc,100*got/best if best else 0))
