import slangpy as spy
import numpy as np, time, pathlib, math
N, BAND, WG, R = 4096, 256, 256, 16
TC = 4.5
dev = spy.Device(type=spy.DeviceType.vulkan)
mod = dev.load_module_from_source("sat", pathlib.Path("occ.slang").read_text())
K = lambda e: dev.create_compute_kernel(dev.link_program([mod],[mod.entry_point(e)]))
kc, kr, kf, kz = K("coarseShuf"), K("refineOcc"), K("fusedOcc"), K("clearCounter")
def mk(n,sz,rw,dat=None):
    return dev.create_buffer(element_count=n, struct_size=sz,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource, data=dat)
def per(fn, reps=3):
    fn(); dev.wait(); best=1e9
    for _ in range(7):
        t0=time.perf_counter()
        for _ in range(reps): fn()
        dev.wait(); best=min(best,(time.perf_counter()-t0)/reps)
    return best
CU = 40
print("Radeon 8060S: %d CUs, ceiling 8953 GFLOP/s\n" % CU)
print("%-9s %-14s %-9s %-10s %-9s %-11s %s"
      % ("pairs","nd x nt","mem MB","flat ms","GFLOP/s","% ceiling","pairs/CU"))
for (nd, nt) in ((16,128),(64,256),(64,512),(128,512),(128,1024),(256,1024)):
    pairs = nd*nt
    rng = np.random.default_rng(0)
    k = np.arange(1, N//2); power = np.zeros(N)
    power[1:N//2] = k**(-7/3.)/((0.015*N/k)**4+1.0); power/=power.sum()
    amp = np.sqrt(power)
    h = (amp*np.exp(2j*np.pi*rng.random((nt,N)))).astype(np.complex64)
    h /= np.linalg.norm(h,axis=1,keepdims=True)
    d = (amp*(rng.standard_normal((nd,N))+1j*rng.standard_normal((nd,N)))).astype(np.complex64)
    bd = mk(d.size,8,False,np.ascontiguousarray(d).view(np.float32))
    bh = mk(h.size,8,False,np.ascontiguousarray(h).view(np.float32))
    bm = mk(pairs,4,True)
    def flat(): kf.dispatch(thread_count=[pairs*WG,1,1], data=bd, tmpl=bh, peakMag=bm, ntmpl=nt)
    t = per(flat)
    fl = pairs*(5.0*N*math.log2(N)+6.0*N)
    mem = (nd+nt)*N*8/1e6
    print("%-9d %-14s %-9.1f %-10.4f %-9.0f %-11.1f %.0f"
          % (pairs, "%dx%d"%(nd,nt), mem, t*1e3, fl/t/1e9, 100*(fl/t/1e9)/8953, pairs/CU))
