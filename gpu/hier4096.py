import slangpy as spy
import numpy as np, time, pathlib, math
N, BAND, WG, R = 4096, 256, 256, 16
THRESH, TC = 5.0, 4.5
dev = spy.Device(type=spy.DeviceType.vulkan)
src = pathlib.Path("occ.slang").read_text()
mod = dev.load_module_from_source("hf", src)
K = lambda e: dev.create_compute_kernel(dev.link_program([mod],[mod.entry_point(e)]))
kc, kr, kf, kz = K("coarseShuf"), K("refineOcc"), K("fusedOcc"), K("clearCounter")

def mk(n,sz,rw,dat=None):
    return dev.create_buffer(element_count=n, struct_size=sz,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource, data=dat)
def per(fn, reps=4):
    fn(); dev.wait(); best=1e9
    for _ in range(9):
        t0=time.perf_counter()
        for _ in range(reps): fn()
        dev.wait(); best=min(best,(time.perf_counter()-t0)/reps)
    return best

print("%-8s %-10s %-10s %-9s %-8s %-10s %s"
      % ("pairs","flat ms","hier ms","speedup","escal.","ideal","% of ideal"))
for (nd, nt) in ((16,128),(64,256),(64,512)):
    pairs = nd*nt
    rng = np.random.default_rng(0)
    k = np.arange(1, N//2); power = np.zeros(N)
    power[1:N//2] = k**(-7/3.)/((0.015*N/k)**4+1.0); power/=power.sum()
    amp = np.sqrt(power)
    h = (amp*np.exp(2j*np.pi*rng.random((nt,N)))).astype(np.complex64)
    h /= np.linalg.norm(h,axis=1,keepdims=True)
    d = (amp*(rng.standard_normal((nd,N))+1j*rng.standard_normal((nd,N)))).astype(np.complex64)
    d /= (np.fft.ifft(d[0]*np.conj(h[0]))*N).real.std()
    for (di,ti,lag,snr) in ((3,21,611,12.),(5,40,100,9.),(0,2,900,7.)):
        d[di] += (snr*h[ti]*np.exp(-2j*np.pi*lag*np.arange(N)/N)).astype(np.complex64)
    bd = mk(d.size,8,False,np.ascontiguousarray(d).view(np.float32))
    bh = mk(h.size,8,False,np.ascontiguousarray(h).view(np.float32))
    bm, bw, bc = mk(pairs,4,True), mk(pairs,4,True), mk(4,4,True)
    gC, gF = (pairs+R-1)//R, pairs
    def flat(): kf.dispatch(thread_count=[gF*WG,1,1], data=bd, tmpl=bh, peakMag=bm, ntmpl=nt)
    def hier():
        kz.dispatch(thread_count=[1,1,1], counter=bc)          # device-side clear
        kc.dispatch(thread_count=[gC*WG,1,1], data=bd, tmpl=bh, peakMag=bm,
                    worklist=bw, counter=bc, ntmpl=nt, nfull=N, npairs=pairs, tcoarse=TC)
        kr.dispatch(thread_count=[gF*WG,1,1], data=bd, tmpl=bh, peakMag=bm,
                    worklist=bw, counter=bc, ntmpl=nt)
    hier(); dev.wait()
    nesc = int(bc.to_numpy().view(np.uint32)[0])
    gm = bm.to_numpy().view(np.float32).reshape(nd,nt)
    ref = np.abs(np.fft.ifft(d[:,None,:]*np.conj(h)[None,:,:],axis=2)*N).max(axis=2)
    above, found = ref > THRESH, gm > THRESH
    tf, th = per(flat), per(hier)
    ideal = 1.0/((BAND*math.log2(BAND))/(N*math.log2(N)) + nesc/pairs)
    print("%-8d %-10.4f %-10.4f %-9.2fx %-8.1f%% %-10.2fx %.0f%%   missed %d, invented %d"
          % (pairs, tf*1e3, th*1e3, tf/th, 100*nesc/pairs, ideal,
             100*(tf/th)/ideal, int((above&~found).sum()), int((found&~above).sum())))
