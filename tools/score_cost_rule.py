#!/usr/bin/env python3
"""Score candidate cost-lookup rules against measured truth."""
import sys, numpy as np, time, matchedfilter as mf
from matchedfilter.benchmark import _inspiral_power

def admissible(p,n,snr,fd,t):
    use,_=mf._snr_rows_for(snr, sorted({r[4] for r in t["fdr"] if r[0]==n}))
    feats,byconf={},{}
    for (tn,band,U,K,ts,tf,tbe,mg,dm) in t["fdr"]:
        if tn!=n or ts not in use or band>=n: continue
        feats.setdefault(band, mf._band_features(p,band))
        byconf.setdefault((band,U,K,mg),[]).append((tf,tbe,dm))
    out=[]
    for c,rows in byconf.items():
        f,be=feats[c[0]]
        fq,bq=min(f,max(r[0] for r in rows)),min(be,max(r[1] for r in rows))
        cov=[dm for (tf,tbe,dm) in rows if tf>=fq-1e-9 and tbe>=bq-1e-9]
        if cov and max(cov)<=fd: out.append((c,fq,bq))
    return out

RULES={
 "covering (f>=ours, max)": lambda rows,fq,bq: (lambda v: max(v) if v else max(r[2] for r in rows))(
     [c for (tf,tbe,c) in rows if tf>=fq-1e-9 and tbe>=bq-1e-9]),
 "pessimistic (f<=ours,max)": lambda rows,fq,bq: (lambda v: max(v) if v else max(r[2] for r in rows))(
     [c for (tf,tbe,c) in rows if tf<=fq+1e-9]),
 "nearest in (f,beff)": lambda rows,fq,bq: min(rows,key=lambda r:((r[0]-fq)/max(fq,1e-9))**2+((r[1]-bq)/max(bq,1e-9))**2)[2],
 "interp in f": lambda rows,fq,bq: float(np.interp(fq, *(lambda d: (sorted(d), [np.mean(d[x]) for x in sorted(d)]))(
     {round(tf,6): [c for (tf2,_,c) in rows if round(tf2,6)==round(tf,6)] for (tf,_,_) in rows}))),
}

def measure(n,snr,fd=1e-3,nd=8,nt=32):
    p=_inspiral_power(n); t=mf._load_tuning()
    adm=admissible(p,n,snr,fd,t)
    rng=np.random.default_rng(7); amp=np.sqrt(p)
    h=(amp*np.exp(1j*rng.uniform(0,2*np.pi,(nt,n)))).astype(np.complex64)
    h/=np.sqrt((np.abs(h)**2).sum(axis=1,keepdims=True))
    d=(rng.standard_normal((nd,n))+1j*rng.standard_normal((nd,n))).astype(np.complex64)
    ws=int(0.2*n)&~15; we=ws+(int(0.6*n)&~15)
    flat=mf.MatchedFilter(n,nd,nt); flat.set_data(d); flat.set_templates(h)
    def per(fn,floor=0.04):
        fn(); k=1
        while True:
            t0=time.perf_counter()
            for _ in range(k): fn()
            dt=time.perf_counter()-t0
            if dt>=floor: return dt/k
            k*=2
    true={}
    for (c,fq,bq) in adm:
        band,U,K,mg=c
        hf=mf.HierarchicalFilter(n,nd,nt,snr,fd,band=band,oversample=U,taps=K)
        hf.set_reference(p); hf._mf.set_coarse_margin(mg); hf.set_data(d); hf.set_templates(h)
        r=[per(lambda: flat.run(binsize=n,threshold=snr,window=(ws,we)))/
           per(lambda: hf.run(binsize=n,threshold=snr,window=(ws,we))) for _ in range(3)]
        true[c]=float(np.median(r))
    best=max(true.values())
    print("  n=%-7d snr %.1f : %d admissible, best measured %.2fx"%(n,snr,len(adm),best))
    for name,rule in RULES.items():
        scored=[]
        for (c,fq,bq) in adm:
            rows=[]
            for cs in mf._cost_snrs(t,n,c[0],c[1],c[2],c[3],(snr,)):
                rows+=t["cost"].get((n,c[0],c[1],c[2],round(cs,2),c[3])) or []
            if rows: scored.append((rule(rows,fq,bq),c))
        if not scored: continue
        pick=min(scored)[1]
        print("     %-26s picks %-18s %.2fx  (%.0f%% of best)"
              %(name,"%d/%d/%d m%.2f"%pick,true[pick],100*true[pick]/best))

for n,snr in ((4096,5.0),(4096,6.0),(8192,5.0),(16384,5.5)):
    measure(n,snr)
