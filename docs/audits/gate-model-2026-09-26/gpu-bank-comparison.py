import sys,time,json
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'tests'))
import matchedfilter as mf
from test_api import inspiral_power,template_with_power
n=4096; nd=16; nt=1024
r=np.random.default_rng(1); d=(r.standard_normal((nd,n))+1j*r.standard_normal((nd,n))).astype('complex64')
p=inspiral_power(n)
r=np.random.default_rng(19)
banks={'old':np.stack([template_with_power(n,inspiral_power(n,exponent=e)) for e in np.linspace(-7/3,-4/3,nt)]),'random':(np.sqrt(p)*np.exp(2j*np.pi*r.random((nt,n)))).astype('complex64')}
banks['random']/=np.linalg.norm(banks['random'],axis=1,keepdims=True)
fs=[]
for name,h in banks.items():
 f=mf.HierarchicalFilter(n,nd,nt,snr=5.5,fd=.01,device='gpu');f.set_reference(p);f.set_data(d);f.set_templates(h)
 fn=lambda f=f:f.run(binsize=n,threshold=5.5)
 fn();fs.append((name,f,fn));print(name,'gate',f._cal_thr,'refine',f.refine_rate,flush=True)
res={k:[] for k,_,_ in fs}
for round in range(9):
 for name,f,fn in fs[::1 if round%2 else -1]:
  end=time.perf_counter()+.15
  while time.perf_counter()<end:fn()
  t=time.perf_counter()
  for i in range(150):fn()
  ms=(time.perf_counter()-t)*1000/150;res[name].append(ms)
print(json.dumps({'package':mf.__file__,'timings':res,'median':{k:float(np.median(v)) for k,v in res.items()}}),flush=True)
