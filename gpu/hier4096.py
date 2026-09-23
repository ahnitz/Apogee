import slangpy as spy
import numpy as np, time, pathlib, math
N, BAND, WG, TPT = 4096, 256, 256, 16
SLOTS = WG // TPT
ND, NT = 16, 128
PAIRS = ND*NT
THRESH, TC = 5.0, 4.5
dev = spy.Device(type=spy.DeviceType.vulkan)
# The coarse pass keeps the DIRECT transpose (reg.slang): at 256 points
# the chunked exchange's 8 barriers cost more than the occupancy it buys,
# which is the opposite trade from n=4096. Measured 0.1269 ms against
# 0.1043 for the direct version.
reg = pathlib.Path("reg.slang").read_text()
reg = reg.replace("""               RWStructuredBuffer<float> peakMag,
               uniform uint ntmpl, uniform uint nfull, uniform uint npairs)""",
"""               RWStructuredBuffer<float> peakMag,
               RWStructuredBuffer<uint> worklist, RWStructuredBuffer<uint> counter,
               uniform uint ntmpl, uniform uint nfull, uniform uint npairs,
               uniform float tcoarse)""")
reg = reg.replace("""    if (lane == 0 && pair < npairs) peakMag[pair] = sqrt(best);""",
"""    if (lane == 0 && pair < npairs) {
        if (sqrt(best) > tcoarse) { uint s2; InterlockedAdd(counter[0], 1u, s2); worklist[s2] = pair; }
        else peakMag[pair] = 0.0f;
    }""")
mc = dev.load_module_from_source("c4", reg)
kc = dev.create_compute_kernel(dev.link_program([mc],[mc.entry_point("coarseReg")]))
mb = dev.load_module_from_source("b4", pathlib.Path("occ.slang").read_text())
kflat = dev.create_compute_kernel(dev.link_program([mb],[mb.entry_point("fusedOcc")]))
kref  = dev.create_compute_kernel(dev.link_program([mb],[mb.entry_point("refineOcc")]))
rng = np.random.default_rng(0)
k = np.arange(1, N//2); power = np.zeros(N)
power[1:N//2] = k**(-7/3.)/((0.015*N/k)**4+1.0); power/=power.sum()
amp = np.sqrt(power)
h = (amp*np.exp(2j*np.pi*rng.random((NT,N)))).astype(np.complex64)
h /= np.linalg.norm(h,axis=1,keepdims=True)
d = (amp*(rng.standard_normal((ND,N))+1j*rng.standard_normal((ND,N)))).astype(np.complex64)
d /= (np.fft.ifft(d[0]*np.conj(h[0]))*N).real.std()
for (di,ti,lag,snr) in ((3,21,611,12.),(5,40,100,9.),(0,2,900,7.),(11,77,2500,8.)):
    d[di] += (snr*h[ti]*np.exp(-2j*np.pi*lag*np.arange(N)/N)).astype(np.complex64)
ref = np.abs(np.fft.ifft(d[:,None,:]*np.conj(h)[None,:,:],axis=2)*N).max(axis=2)
above = ref > THRESH
def mk(n,sz,rw,dat=None):
    return dev.create_buffer(element_count=n, struct_size=sz,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource, data=dat)
bd = mk(d.size,8,False,np.ascontiguousarray(d).view(np.float32))
bh = mk(h.size,8,False,np.ascontiguousarray(h).view(np.float32))
bm, bw, bc, bdump = mk(PAIRS,4,True), mk(PAIRS,4,True), mk(4,4,True), mk(N,8,True)
def flat(): kflat.dispatch(thread_count=[PAIRS*WG,1,1], data=bd, tmpl=bh, peakMag=bm, ntmpl=NT)
def hier():
    bc.copy_from_numpy(np.zeros(4,np.uint32))
    kc.dispatch(thread_count=[((PAIRS+SLOTS-1)//SLOTS)*WG,1,1], data=bd, tmpl=bh,
                peakMag=bm, worklist=bw, counter=bc, ntmpl=NT, nfull=N, npairs=PAIRS, tcoarse=TC)
    kref.dispatch(thread_count=[PAIRS*WG,1,1], data=bd, tmpl=bh, peakMag=bm,
                  worklist=bw, counter=bc, ntmpl=NT)
def per(fn,floor=0.05):
    fn(); dev.wait(); c=1
    while True:
        t0=time.perf_counter()
        for _ in range(c): fn()
        dev.wait(); dt=time.perf_counter()-t0
        if dt>=floor: return dt/c
        c*=2
hier(); dev.wait()
nesc = int(bc.to_numpy().view(np.uint32)[0])
gm = bm.to_numpy().view(np.float32).reshape(ND,NT)
found = gm > THRESH
print("n=%d band=%d, %d pairs, escalated %d (%.1f%%), missed %d, invented %d"
      % (N, BAND, PAIRS, nesc, 100*nesc/PAIRS,
         int((above & ~found).sum()), int((found & ~above).sum())))
tf = min(per(flat) for _ in range(3)); th = min(per(hier) for _ in range(3))
ideal = 1.0/((BAND*math.log2(BAND))/(N*math.log2(N)) + nesc/PAIRS)
print("flat %.4f ms   hierarchical %.4f ms   %.2fx   ideal %.2fx  -> %.0f%% of ideal"
      % (tf*1e3, th*1e3, tf/th, ideal, 100*(tf/th)/ideal))
