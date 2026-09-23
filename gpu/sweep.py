import slangpy as spy
import numpy as np, time, pathlib

N, BAND, WG = 1024, 256, 256
ND, NT = 32, 256          # 8192 pairs: enough to fill 40 CUs
PAIRS = ND * NT
THRESH = 5.0

dev = spy.Device(type=spy.DeviceType.vulkan)
src = pathlib.Path("fh.slang").read_text()

rng = np.random.default_rng(0)
k = np.arange(1, N // 2)
power = np.zeros(N); power[1:N//2] = k**(-7/3.) / ((0.015*N/k)**4 + 1.0)
power /= power.sum(); amp = np.sqrt(power)
h = (amp * np.exp(2j*np.pi*rng.random((NT, N)))).astype(np.complex64)
h /= np.linalg.norm(h, axis=1, keepdims=True)
d = (amp * (rng.standard_normal((ND, N)) + 1j*rng.standard_normal((ND, N)))).astype(np.complex64)
d /= (np.fft.ifft(d[0] * np.conj(h[0])) * N).real.std()
for (di, ti, lag, snr) in ((3, 21, 611, 12.0), (5, 40, 100, 9.0), (0, 2, 900, 7.0), (17, 200, 55, 8.0)):
    d[di] += (snr * h[ti] * np.exp(-2j*np.pi*lag*np.arange(N)/N)).astype(np.complex64)

ref = np.abs(np.fft.ifft(d[:, None, :] * np.conj(h)[None, :, :], axis=2) * N)
rmag, ridx = ref.max(axis=2), ref.argmax(axis=2)
above = rmag > THRESH
print("pairs %d, %d truly above %.1f, in-band fraction %.3f"
      % (PAIRS, int(above.sum()), THRESH, power[:BAND].sum()))

def mkbuf(n, sz, rw, data=None):
    return dev.create_buffer(element_count=n, struct_size=sz,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource,
        data=data)
bd = mkbuf(d.size, 8, False, np.ascontiguousarray(d).view(np.float32))
bh = mkbuf(h.size, 8, False, np.ascontiguousarray(h).view(np.float32))
bmag, bidx = mkbuf(PAIRS, 4, True), mkbuf(PAIRS, 4, True)
besc = mkbuf(4, 4, True)

def per(fn, floor=0.05):
    fn(); dev.wait(); k2 = 1
    while True:
        t0 = time.perf_counter()
        for _ in range(k2): fn()
        dev.wait(); dt = time.perf_counter() - t0
        if dt >= floor: return dt / k2
        k2 *= 2

print("\n%-6s %-5s %-18s %-10s %-9s %s"
      % ("TILE", "TP", "escalated", "ms", "vs flat", "correctness"))
fmod = dev.load_module_from_source("flat", pathlib.Path("mf.slang").read_text())
fk = dev.create_compute_kernel(dev.link_program([fmod], [fmod.entry_point("fused")]))
def goflat():
    fk.dispatch(thread_count=[PAIRS*WG,1,1], data=bd, tmpl=bh,
                peakMag=bmag, peakIdx=bidx, ntmpl=NT)
FLAT = min(per(goflat) for _ in range(3))
goflat(); dev.wait()
fm = bmag.to_numpy().view(np.float32).reshape(ND, NT)
fi = bidx.to_numpy().view(np.uint32).reshape(ND, NT)
print("flat kernel: %.4f ms, peaks exact %d/%d"
      % (FLAT*1e3, int((fi == ridx).sum()), PAIRS))
for tile in (4, 8):
    body = src.replace("#define TILE 8", "#define TILE %d" % tile)
    mod = dev.load_module_from_source("fh%d" % tile, body)
    kern = dev.create_compute_kernel(dev.link_program([mod], [mod.entry_point("fusedHier")]))
    groups = (PAIRS + tile - 1) // tile
    for tc in (0.0, 4.5, 1e9):
        def go():
            besc.copy_from_numpy(np.zeros(4, np.uint32))
            kern.dispatch(thread_count=[groups*WG,1,1], data=bd, tmpl=bh,
                          peakMag=bmag, peakIdx=bidx, escalated=besc,
                          ntmpl=NT, tcoarse=tc, npairs=PAIRS)
        go(); dev.wait()
        nesc = int(besc.to_numpy().view(np.uint32)[0])
        gmag = bmag.to_numpy().view(np.float32).reshape(ND, NT)
        gidx = bidx.to_numpy().view(np.uint32).reshape(ND, NT)
        found = (gmag > THRESH) & (gidx == ridx)
        missed = int((above & ~found).sum())
        inv = int(((gmag > THRESH) & ~above).sum())
        t = min(per(go) for _ in range(3))
        tag = ("ALL" if nesc == PAIRS else ("NONE" if nesc == 0 else "%d" % nesc))
        print("%-6d %-5d %-18s %-10.4f %-9.2fx missed %d, invented %d"
              % (tile, WG//tile, "%s/%d" % (tag, PAIRS), t*1e3, FLAT/t, missed, inv))
