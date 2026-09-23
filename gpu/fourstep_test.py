import slangpy as spy
import numpy as np, time, pathlib
LEN, WG, TPT = 256, 256, 16
SLOTS = WG // TPT
NFULL = 1024
ND, NT = 32, 256
PAIRS = ND*NT
dev = spy.Device(type=spy.DeviceType.vulkan)
mod = dev.load_module_from_source("r", pathlib.Path("reg.slang").read_text())
kern = dev.create_compute_kernel(dev.link_program([mod],[mod.entry_point("coarseReg")]))

rng = np.random.default_rng(0)
k = np.arange(1, NFULL//2); power = np.zeros(NFULL)
power[1:NFULL//2] = k**(-7/3.)/((0.015*NFULL/k)**4+1.0); power/=power.sum()
amp = np.sqrt(power)
h = (amp*np.exp(2j*np.pi*rng.random((NT,NFULL)))).astype(np.complex64)
h /= np.linalg.norm(h,axis=1,keepdims=True)
d = (amp*(rng.standard_normal((ND,NFULL))+1j*rng.standard_normal((ND,NFULL)))).astype(np.complex64)
def mk(n,sz,rw,dat=None):
    return dev.create_buffer(element_count=n, struct_size=sz,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource, data=dat)
bd = mk(d.size,8,False,np.ascontiguousarray(d).view(np.float32))
bh = mk(h.size,8,False,np.ascontiguousarray(h).view(np.float32))
bm = mk(PAIRS,4,True)
groups = (PAIRS + SLOTS - 1)//SLOTS
def go():
    kern.dispatch(thread_count=[groups*WG,1,1], data=bd, tmpl=bh, peakMag=bm,
                  ntmpl=NT, nfull=NFULL, npairs=PAIRS)
go(); dev.wait()
got = bm.to_numpy().view(np.float32).reshape(ND,NT)
# reference: coarse peak = max |ifft of the low BAND bins|
prod = d[:,None,:LEN] * np.conj(h)[None,:,:LEN]
ref = np.abs(np.fft.ifft(prod, axis=2) * LEN).max(axis=2)
rel = np.abs(got-ref)/np.maximum(ref,1e-30)
print("register four-step coarse: max rel err %.2e  median %.2e" % (rel.max(), np.median(rel)))
def per(fn,floor=0.05):
    fn(); dev.wait(); c=1
    while True:
        t0=time.perf_counter()
        for _ in range(c): fn()
        dev.wait(); dt=time.perf_counter()-t0
        if dt>=floor: return dt/c
        c*=2
t = min(per(go) for _ in range(3))
print("  %.4f ms   (radix-4 Stockham coarse pass was 0.180 ms)" % (t*1e3))
