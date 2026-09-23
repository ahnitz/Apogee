# Two kernels instead of one: the register-resident batched coarse pass,
# then a separate refine dispatch over the survivors. Each gets its own
# register and LDS budget, at the cost of a worklist through global memory.
import slangpy as spy
import numpy as np, time, pathlib
N, BAND, WG, TPT = 1024, 256, 256, 16
SLOTS = WG // TPT
ND, NT = 32, 256
PAIRS = ND*NT
THRESH, TC = 5.0, 4.5
dev = spy.Device(type=spy.DeviceType.vulkan)

reg = pathlib.Path("reg.slang").read_text()
# coarse kernel: emit a worklist instead of just the magnitude
reg = reg.replace('''               RWStructuredBuffer<float> peakMag,
               uniform uint ntmpl, uniform uint nfull, uniform uint npairs)''',
'''               RWStructuredBuffer<float> peakMag, RWStructuredBuffer<uint> peakIdx,
               RWStructuredBuffer<uint> worklist, RWStructuredBuffer<uint> counter,
               uniform uint ntmpl, uniform uint nfull, uniform uint npairs,
               uniform float tcoarse)''')
reg = reg.replace('''    if (lane == 0 && pair < npairs) peakMag[pair] = sqrt(best);''',
'''    if (lane == 0 && pair < npairs) {
        if (sqrt(best) > tcoarse) {
            uint s2; InterlockedAdd(counter[0], 1u, s2); worklist[s2] = pair;
        } else { peakMag[pair] = 0.0f; peakIdx[pair] = 0xffffffffu; }
    }''')
mc = dev.load_module_from_source("c", reg)
kc = dev.create_compute_kernel(dev.link_program([mc],[mc.entry_point("coarseReg")]))
mh = dev.load_module_from_source("hh", pathlib.Path("hier.slang").read_text())
kr = dev.create_compute_kernel(dev.link_program([mh],[mh.entry_point("refine")]))
mf = dev.load_module_from_source("ff", pathlib.Path("mf.slang").read_text())
kf = dev.create_compute_kernel(dev.link_program([mf],[mf.entry_point("fused")]))

rng = np.random.default_rng(0)
k = np.arange(1, N//2); power = np.zeros(N)
power[1:N//2] = k**(-7/3.)/((0.015*N/k)**4+1.0); power/=power.sum()
amp = np.sqrt(power)
h = (amp*np.exp(2j*np.pi*rng.random((NT,N)))).astype(np.complex64)
h /= np.linalg.norm(h,axis=1,keepdims=True)
d = (amp*(rng.standard_normal((ND,N))+1j*rng.standard_normal((ND,N)))).astype(np.complex64)
d /= (np.fft.ifft(d[0]*np.conj(h[0]))*N).real.std()
for (di,ti,lag,snr) in ((3,21,611,12.),(5,40,100,9.),(0,2,900,7.),(17,200,55,8.)):
    d[di] += (snr*h[ti]*np.exp(-2j*np.pi*lag*np.arange(N)/N)).astype(np.complex64)
ref = np.abs(np.fft.ifft(d[:,None,:]*np.conj(h)[None,:,:],axis=2)*N)
rmag, ridx = ref.max(axis=2), ref.argmax(axis=2)
above = rmag > THRESH

def mk(n,sz,rw,dat=None):
    return dev.create_buffer(element_count=n, struct_size=sz,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource, data=dat)
bd = mk(d.size,8,False,np.ascontiguousarray(d).view(np.float32))
bh = mk(h.size,8,False,np.ascontiguousarray(h).view(np.float32))
bm,bi = mk(PAIRS,4,True), mk(PAIRS,4,True)
bw,bc = mk(PAIRS,4,True), mk(4,4,True)

def coarse():
    kc.dispatch(thread_count=[((PAIRS+SLOTS-1)//SLOTS)*WG,1,1], data=bd, tmpl=bh,
                peakMag=bm, peakIdx=bi, worklist=bw, counter=bc,
                ntmpl=NT, nfull=N, npairs=PAIRS, tcoarse=TC)
def refine():
    kr.dispatch(thread_count=[PAIRS*WG,1,1], data=bd, tmpl=bh, peakMag=bm,
                peakIdx=bi, worklist=bw, counter=bc, ntmpl=NT)
def both():
    bc.copy_from_numpy(np.zeros(4,np.uint32)); coarse(); refine()
def flat():
    kf.dispatch(thread_count=[PAIRS*WG,1,1], data=bd, tmpl=bh, peakMag=bm, peakIdx=bi, ntmpl=NT)

def per(fn,floor=0.05):
    fn(); dev.wait(); c=1
    while True:
        t0=time.perf_counter()
        for _ in range(c): fn()
        dev.wait(); dt=time.perf_counter()-t0
        if dt>=floor: return dt/c
        c*=2

both(); dev.wait()
nesc = int(bc.to_numpy().view(np.uint32)[0])
gm = bm.to_numpy().view(np.float32).reshape(ND,NT)
gi = bi.to_numpy().view(np.uint32).reshape(ND,NT)
found = (gm > THRESH) & (gi == ridx)
print("escalated %d/%d, missed %d, invented %d"
      % (nesc, PAIRS, int((above & ~found).sum()), int(((gm>THRESH)&~above).sum())))
tf = min(per(flat) for _ in range(3))
tc_ = min(per(lambda: (bc.copy_from_numpy(np.zeros(4,np.uint32)), coarse())) for _ in range(3))
tb = min(per(both) for _ in range(3))
print("flat            %.4f ms" % (tf*1e3))
print("coarse only     %.4f ms" % (tc_*1e3))
print("coarse+refine   %.4f ms   %.2fx vs flat" % (tb*1e3, tf/tb))
import math
ideal = 1.0/((BAND*math.log2(BAND))/(N*math.log2(N)) + nesc/PAIRS)
print("ideal for this band/n and escalation: %.2fx  -> reaching %.0f%%"
      % (ideal, 100*(tf/tb)/ideal))
