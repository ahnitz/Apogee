import slangpy as spy
import numpy as np, time, pathlib
N, WG = 4096, 256
ND, NT = 16, 128
PAIRS = ND*NT
dev = spy.Device(type=spy.DeviceType.vulkan)
src = pathlib.Path("big_probe.slang").read_text()
rng = np.random.default_rng(0)
d = (rng.standard_normal((ND,N))+1j*rng.standard_normal((ND,N))).astype(np.complex64)
h = (rng.standard_normal((NT,N))+1j*rng.standard_normal((NT,N))).astype(np.complex64)
def mk(n,sz,rw,dat=None):
    return dev.create_buffer(element_count=n, struct_size=sz,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource, data=dat)
bd = mk(d.size,8,False,np.ascontiguousarray(d).view(np.float32))
bh = mk(h.size,8,False,np.ascontiguousarray(h).view(np.float32))
bm, bdump = mk(PAIRS,4,True), mk(N,8,True)
for tag, pre in (("normal", ""), ("cache probe (one slice)", "#define CACHE_PROBE 1\n")):
    mod = dev.load_module_from_source("bp"+tag[:4], pre+src)
    kern = dev.create_compute_kernel(dev.link_program([mod],[mod.entry_point("fusedBig")]))
    def go(): kern.dispatch(thread_count=[PAIRS*WG,1,1], data=bd, tmpl=bh, peakMag=bm,
                            dump=bdump, ntmpl=NT, dumpPair=999999)
    go(); dev.wait()
    best = 1e9
    for _ in range(9):
        t0=time.perf_counter()
        for _ in range(4): go()
        dev.wait(); best = min(best,(time.perf_counter()-t0)/4)
    print("%-26s %8.4f ms" % (tag, best*1e3))
