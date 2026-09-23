import slangpy as spy
import numpy as np, time, pathlib
N, WG = 4096, 256
ND, NT = 16, 128
PAIRS = ND*NT
dev = spy.Device(type=spy.DeviceType.vulkan)
mod = dev.load_module_from_source("nz", pathlib.Path("big.slang").read_text())
kern = dev.create_compute_kernel(dev.link_program([mod],[mod.entry_point("fusedBig")]))
rng = np.random.default_rng(0)
d = (rng.standard_normal((ND,N))+1j*rng.standard_normal((ND,N))).astype(np.complex64)
h = (rng.standard_normal((NT,N))+1j*rng.standard_normal((NT,N))).astype(np.complex64)
def mk(n,sz,rw,dat=None):
    return dev.create_buffer(element_count=n, struct_size=sz,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource, data=dat)
bd = mk(d.size,8,False,np.ascontiguousarray(d).view(np.float32))
bh = mk(h.size,8,False,np.ascontiguousarray(h).view(np.float32))
bm, bdump = mk(PAIRS,4,True), mk(N,8,True)
def go(): kern.dispatch(thread_count=[PAIRS*WG,1,1], data=bd, tmpl=bh, peakMag=bm,
                        dump=bdump, ntmpl=NT, dumpPair=999999)
def per(floor=0.05):
    go(); dev.wait(); c=1
    while True:
        t0=time.perf_counter()
        for _ in range(c): go()
        dev.wait(); dt=time.perf_counter()-t0
        if dt>=floor: return dt/c
        c*=2
ts = [per() for _ in range(15)]
ts = np.array(ts)*1e3
print("same kernel, same data, 15 independent timings (ms):")
print("  min %.4f  median %.4f  max %.4f   spread %.2fx  CV %.1f%%"
      % (ts.min(), np.median(ts), ts.max(), ts.max()/ts.min(), 100*ts.std()/ts.mean()))
