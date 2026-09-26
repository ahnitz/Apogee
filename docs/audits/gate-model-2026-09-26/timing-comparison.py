import time,json,sys,numpy as np
import matchedfilter as mf
from matchedfilter.benchmark import _inspiral_power
cases=[(1024,5.),(4096,5.),(4096,6.),(16384,5.),(16384,6.)]
if sys.argv[1]=='choices':
 result=[]
 for n,snr in cases:
  p=_inspiral_power(n); t=time.perf_counter(); cfg=mf.choose_config(p,n,snr,.001)
  elapsed=time.perf_counter()-t
  result.append(dict(n=n,snr=snr,cfg=cfg,gate=mf.choose_threshold(p,n,snr,.001,cfg[0]),init_s=elapsed))
 print(json.dumps(result));sys.exit()
old=json.load(open('/tmp/gate-old-choices.json')); result=[]
for record in old:
 n,snr=record['n'],record['snr'];p=_inspiral_power(n);t=time.perf_counter();cfg=mf.choose_config(p,n,snr,.001);cold=time.perf_counter()-t
 rng=np.random.default_rng(619);nd,nt=8,32
 h=(np.sqrt(p)*np.exp(2j*np.pi*rng.random((nt,n)))).astype(np.complex64)
 d=(rng.normal(size=(nd,n))+1j*rng.normal(size=(nd,n))).astype(np.complex64)
 plans={}
 configs={'old':tuple(record['cfg']),'new':cfg,'old_band_new_gate':tuple(record['cfg'])}
 for name,c in configs.items():
  gate=record['gate'] if name=='old' else mf.choose_threshold(p,n,snr,.001,c[0])
  f=mf.HierarchicalFilter(n,nd,nt,snr,.001,band=c[0],taps=c[1]);f.set_reference(p);f.set_coarse_threshold(gate);f.set_templates(h);f.set_data(d);f.run(threshold=snr)
  plans[name]=f
 timings={k:[] for k in plans}
 for rep in range(9):
  for name in rng.permutation(list(plans)):
   f=plans[name];t=time.perf_counter()
   for _ in range(20): f.run(threshold=snr,raw=True)
   timings[name].append((time.perf_counter()-t)/20)
 t=time.perf_counter()
 for _ in range(10): mf.choose_config(p,n,snr,.001)
 hot=(time.perf_counter()-t)/10
 row=dict(n=n,snr=snr,old_cfg=record['cfg'],new_cfg=cfg,old_gate=record['gate'],new_gate=mf.choose_threshold(p,n,snr,.001,cfg[0]),cold_s=cold,hot_s=hot,timing_ms={k:float(np.median(v))*1000 for k,v in timings.items()},refine={k:f.refine_rate for k,f in plans.items()})
 print(json.dumps(row),flush=True);result.append(row)
