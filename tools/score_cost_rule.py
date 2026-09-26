#!/usr/bin/env python3
"""Score cost interpolation rules against measured model-gated alternatives."""
import sys, numpy as np, time, matchedfilter as mf
from matchedfilter.benchmark import _inspiral_power

def admissible(p,n,snr,fd,t):
    """[(band, U, K, f, beff, cost rows)] with a resolvable model gate."""
    return [(c["band"],c["U"],c["K"],c["f"],c["beff"],c["crows"])
            for c in mf._cost_candidates(p,n,snr,t,fd)
            if mf.choose_threshold(p,n,snr,fd,c["band"]) is not None]


def _plane(rows, fq, bq, k=6):
    """Local linear fit in (f, B_eff), evaluated at the query.

    The covering rule takes the worst row at least as high in BOTH features.
    That is right for dismissal, which rises with f, and backwards for cost,
    which falls with it -- so the substitute row always describes an easier
    problem.  Measured at n=4096 snr 6.0 the two features each move the
    K4-against-K8 ratio by about 0.09 and only together cross 1.0, and the
    joint move (-0.155) is close to the sum of the separate ones (-0.175).
    Near-additive over that span is exactly what a plane can represent and
    what interpolating one axis alone cannot.
    """
    pts = np.array([[r[0], r[1], r[2]] for r in rows], float)
    if len(pts) < 3:
        return float(np.mean(pts[:, 2]))
    sf = max(np.std(pts[:, 0]), 1e-6)
    sb = max(np.std(pts[:, 1]), 1e-6)
    dist = ((pts[:, 0] - fq) / sf) ** 2 + ((pts[:, 1] - bq) / sb) ** 2
    idx = np.argsort(dist)[:max(k, 3)]
    q = pts[idx]
    A = np.vstack([np.ones(len(q)), q[:, 0], q[:, 1]]).T
    try:
        coef, *_ = np.linalg.lstsq(A, q[:, 2], rcond=None)
    except np.linalg.LinAlgError:
        return float(np.mean(q[:, 2]))
    return float(coef[0] + coef[1] * fq + coef[2] * bq)


def _idw(rows, fq, bq, k=4, power=2.0):
    """Inverse-distance weighted mean over the k nearest rows."""
    pts = np.array([[r[0], r[1], r[2]] for r in rows], float)
    sf = max(np.std(pts[:, 0]), 1e-6)
    sb = max(np.std(pts[:, 1]), 1e-6)
    d2 = ((pts[:, 0] - fq) / sf) ** 2 + ((pts[:, 1] - bq) / sb) ** 2
    idx = np.argsort(d2)[:k]
    d = np.sqrt(d2[idx])
    if d.min() < 1e-9:
        return float(pts[idx][np.argmin(d), 2])
    w = 1.0 / d ** power
    return float((w * pts[idx, 2]).sum() / w.sum())


RULES={
 "covering (f>=ours, max)": lambda rows,fq,bq: (lambda v: max(v) if v else max(r[2] for r in rows))(
     [c for (tf,tbe,c) in rows if tf>=fq-1e-9 and tbe>=bq-1e-9]),
 "pessimistic (f<=ours,max)": lambda rows,fq,bq: (lambda v: max(v) if v else max(r[2] for r in rows))(
     [c for (tf,tbe,c) in rows if tf<=fq+1e-9]),
 "nearest in (f,beff)": lambda rows,fq,bq: min(rows,key=lambda r:((r[0]-fq)/max(fq,1e-9))**2+((r[1]-bq)/max(bq,1e-9))**2)[2],
 "interp in f": lambda rows,fq,bq: float(np.interp(fq, *(lambda d: (sorted(d), [np.mean(d[x]) for x in sorted(d)]))(
     {round(tf,6): [c for (tf2,_,c) in rows if round(tf2,6)==round(tf,6)] for (tf,_,_) in rows}))),
 "plane fit (f,beff) k=6": lambda rows,fq,bq: _plane(rows,fq,bq,6),
 "plane fit (f,beff) k=4": lambda rows,fq,bq: _plane(rows,fq,bq,4),
 "IDW (f,beff) k=4": lambda rows,fq,bq: _idw(rows,fq,bq,4),
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
    for (band,U,K,fq,bq,crows) in adm:
        key=(band,K)
        if key in true: continue
        hf=mf.HierarchicalFilter(n,nd,nt,snr,fd,band=band,taps=K)
        hf.set_reference(p); hf.set_data(d); hf.set_templates(h)
        r=[per(lambda: flat.run(binsize=n,threshold=snr,window=(ws,we)))/
           per(lambda: hf.run(binsize=n,threshold=snr,window=(ws,we))) for _ in range(3)]
        true[key]=float(np.median(r))
    if not true:
        print("  n=%-7d snr %.1f : nothing admissible"%(n,snr)); return
    best=max(true.values())
    print("  n=%-7d snr %.1f : %d admissible, %d distinct filters, "
          "best measured %.2fx"%(n,snr,len(adm),len(true),best))
    for name,rule in RULES.items():
        scored=[]
        for (band,U,K,fq,bq,crows) in adm:
            if crows: scored.append((rule(crows,fq,bq),(band,K)))
        if not scored: continue
        pick=min(scored)[1]
        print("     %-26s picks %-18s %.2fx  (%.0f%% of best)"
              %(name,"band %d / K %d"%pick,true[pick],100*true[pick]/best))

if __name__ == "__main__":
    for n,snr in ((4096,5.0),(4096,6.0),(4096,6.5),(8192,5.0),(8192,6.0),(16384,5.5)):
        measure(n,snr)
