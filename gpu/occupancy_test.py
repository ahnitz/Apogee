import slangpy as spy
import numpy as np, time, pathlib
N, WG = 4096, 256
ND, NT = 16, 128
PAIRS = ND*NT
dev = spy.Device(type=spy.DeviceType.vulkan)
rng = np.random.default_rng(0)
d = (rng.standard_normal((ND,N))+1j*rng.standard_normal((ND,N))).astype(np.complex64)
h = (rng.standard_normal((NT,N))+1j*rng.standard_normal((NT,N))).astype(np.complex64)
def mk(n,sz,rw,dat=None):
    return dev.create_buffer(element_count=n, struct_size=sz,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource, data=dat)
bd = mk(d.size,8,False,np.ascontiguousarray(d).view(np.float32))
bh = mk(h.size,8,False,np.ascontiguousarray(h).view(np.float32))
bm, bdump = mk(PAIRS,4,True), mk(N,8,True)
ref = np.abs(np.fft.ifft(d[:,None,:]*np.conj(h)[None,:,:],axis=2)*N).max(axis=2)

def bench(name, src, entry, extra):
    mod = dev.load_module_from_source(name, src)
    kern = dev.create_compute_kernel(dev.link_program([mod],[mod.entry_point(entry)]))
    def go(): kern.dispatch(thread_count=[PAIRS*WG,1,1], data=bd, tmpl=bh,
                            peakMag=bm, ntmpl=NT, **extra)
    go(); dev.wait()
    got = bm.to_numpy().view(np.float32).reshape(ND,NT)
    rel = np.abs(got-ref)/np.maximum(ref,1e-30)
    best = 1e9
    for _ in range(11):
        t0=time.perf_counter()
        for _ in range(4): go()
        dev.wait(); best=min(best,(time.perf_counter()-t0)/4)
    fl = PAIRS*(5.0*N*np.log2(N)+6.0*N)
    print("%-28s %8.4f ms  %6.0f GFLOP/s  max rel err %.2e"
          % (name, best*1e3, fl/best/1e9, rel.max()))
    return best

t_old = bench("32 KB, whole transform", pathlib.Path("big.slang").read_text(),
              "fusedBig", dict(dump=bdump, dumpPair=999999))
t_new = bench("8 KB, chunked exchange", pathlib.Path("occ.slang").read_text(),
              "fusedOcc", {})
print("\nchunked is %.2fx" % (t_old/t_new))
