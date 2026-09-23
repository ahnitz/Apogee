import slangpy as spy
import numpy as np, time, pathlib
N, WG = 4096, 256
ND, NT = 16, 128
PAIRS = ND*NT
dev = spy.Device(type=spy.DeviceType.vulkan)
mod = dev.load_module_from_source("b", pathlib.Path("big.slang").read_text())
kern = dev.create_compute_kernel(dev.link_program([mod],[mod.entry_point("fusedBig")]))
rng = np.random.default_rng(0)
k = np.arange(1, N//2); power = np.zeros(N)
power[1:N//2] = k**(-7/3.)/((0.015*N/k)**4+1.0); power/=power.sum()
amp = np.sqrt(power)
h = (amp*np.exp(2j*np.pi*rng.random((NT,N)))).astype(np.complex64)
h /= np.linalg.norm(h,axis=1,keepdims=True)
d = (amp*(rng.standard_normal((ND,N))+1j*rng.standard_normal((ND,N)))).astype(np.complex64)
def mk(n,sz,rw,dat=None):
    return dev.create_buffer(element_count=n, struct_size=sz,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource, data=dat)
bd = mk(d.size,8,False,np.ascontiguousarray(d).view(np.float32))
bh = mk(h.size,8,False,np.ascontiguousarray(h).view(np.float32))
bm = mk(PAIRS,4,True)
bdump = mk(N,8,True)
def go(): kern.dispatch(thread_count=[PAIRS*WG,1,1], data=bd, tmpl=bh, peakMag=bm, dump=bdump, ntmpl=NT, dumpPair=0)
go(); dev.wait()
got = bm.to_numpy().view(np.float32).reshape(ND,NT)
ref = np.abs(np.fft.ifft(d[:,None,:]*np.conj(h)[None,:,:],axis=2)*N).max(axis=2)
rel = np.abs(got-ref)/np.maximum(ref,1e-30)

g = bdump.to_numpy().view(np.complex64)
w = np.fft.ifft(d[0]*np.conj(h[0]))*N
print("sorted magnitudes match set: %s  (max err %.2e)"
      % (np.allclose(np.sort(np.abs(g)), np.sort(np.abs(w)), atol=1e-4),
         np.abs(np.sort(np.abs(g))-np.sort(np.abs(w))).max()))
print("elementwise (natural order) max err %.2e" % np.abs(g-w).max())
print("n=4096 nested four-step: max rel err %.2e  median %.2e" % (rel.max(), np.median(rel)))
def per(fn,floor=0.05):
    fn(); dev.wait(); c=1
    while True:
        t0=time.perf_counter()
        for _ in range(c): fn()
        dev.wait(); dt=time.perf_counter()-t0
        if dt>=floor: return dt/c
        c*=2
t = min(per(go) for _ in range(3))
fl = PAIRS*(5.0*N*np.log2(N)+6.0*N)
print("  %.4f ms   %.0f GFLOP/s   (%d pairs)" % (t*1e3, fl/t/1e9, PAIRS))
