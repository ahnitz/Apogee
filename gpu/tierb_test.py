import slangpy as spy
import numpy as np, time, pathlib
dev = spy.Device(type=spy.DeviceType.vulkan)
src = pathlib.Path("tierb.slang").read_text()
print("%-8s %-7s %-12s %-11s %s" % ("n","threads","max rel err","ms","GFLOP/s"))
for N in (1024, 2048, 4096, 8192, 16384):
    WG = N // 16
    ND, NT = 8, 64
    PAIRS = ND*NT
    mod = dev.load_module_from_source("tb%d"%N, ("#define NLEN %d\n"%N)+src)
    kern = dev.create_compute_kernel(dev.link_program([mod],[mod.entry_point("fusedTierB")]))
    rng = np.random.default_rng(0)
    d = (rng.standard_normal((ND,N))+1j*rng.standard_normal((ND,N))).astype(np.complex64)
    h = (rng.standard_normal((NT,N))+1j*rng.standard_normal((NT,N))).astype(np.complex64)
    def mk(n,sz,rw,dat=None):
        return dev.create_buffer(element_count=n, struct_size=sz,
            usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource, data=dat)
    bd = mk(d.size,8,False,np.ascontiguousarray(d).view(np.float32))
    bh = mk(h.size,8,False,np.ascontiguousarray(h).view(np.float32))
    bm = mk(PAIRS,4,True)
    def go(): kern.dispatch(thread_count=[PAIRS*WG,1,1], data=bd, tmpl=bh, peakMag=bm, ntmpl=NT)
    go(); dev.wait()
    got = bm.to_numpy().view(np.float32).reshape(ND,NT)
    ref = np.abs(np.fft.ifft(d[:,None,:]*np.conj(h)[None,:,:],axis=2)*N).max(axis=2)
    rel = np.abs(got-ref)/np.maximum(ref,1e-30)
    best=1e9
    for _ in range(7):
        t0=time.perf_counter()
        for _ in range(4): go()
        dev.wait(); best=min(best,(time.perf_counter()-t0)/4)
    fl = PAIRS*(5.0*N*np.log2(N)+6.0*N)
    print("%-8d %-7d %-12.2e %-11.4f %.0f  %s"
          % (N, WG, rel.max(), best*1e3, fl/best/1e9,
             "OK" if rel.max() < 1e-4 else "WRONG"))
