import slangpy as spy
import numpy as np, time, pathlib
N, BAND, WG, TILE = 1024, 256, 256, 8   # must match the shader default
ND, NT = 32, 256
PAIRS = ND*NT
dev = spy.Device(type=spy.DeviceType.vulkan)
src = pathlib.Path("fh_probe.slang").read_text()
rng = np.random.default_rng(0)
k = np.arange(1, N//2); power = np.zeros(N)
power[1:N//2] = k**(-7/3.)/((0.015*N/k)**4+1.0); power /= power.sum()
amp = np.sqrt(power)
h = (amp*np.exp(2j*np.pi*rng.random((NT,N)))).astype(np.complex64)
h /= np.linalg.norm(h,axis=1,keepdims=True)
d = (amp*(rng.standard_normal((ND,N))+1j*rng.standard_normal((ND,N)))).astype(np.complex64)
def mk(n,sz,rw,dat=None):
    return dev.create_buffer(element_count=n, struct_size=sz,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource, data=dat)
bd = mk(d.size,8,False,np.ascontiguousarray(d).view(np.float32))
bh = mk(h.size,8,False,np.ascontiguousarray(h).view(np.float32))
bm,bi,be = mk(PAIRS,4,True), mk(PAIRS,4,True), mk(4,4,True)
def per(fn,floor=0.05):
    fn(); dev.wait(); c=1
    while True:
        t0=time.perf_counter()
        for _ in range(c): fn()
        dev.wait(); dt=time.perf_counter()-t0
        if dt>=floor: return dt/c
        c*=2
for tag, defs in (("normal (57x redundant reads)", ""), ("cache probe (one slice)", "#define CACHE_PROBE 1\n")):
    body = defs + src
    mod = dev.load_module_from_source("p"+tag[:4], body)
    kern = dev.create_compute_kernel(dev.link_program([mod],[mod.entry_point("fusedHier")]))
    groups = (PAIRS+TILE-1)//TILE
    def go():
        be.copy_from_numpy(np.zeros(4,np.uint32))
        kern.dispatch(thread_count=[groups*WG,1,1], data=bd, tmpl=bh, peakMag=bm,
                      peakIdx=bi, escalated=be, ntmpl=NT, tcoarse=1e9, npairs=PAIRS)
    t = min(per(go) for _ in range(3))
    traffic = PAIRS*2*BAND*8
    print("%-32s %8.4f ms   %6.1f GB/s equivalent" % (tag, t*1e3, traffic/t/1e9))
