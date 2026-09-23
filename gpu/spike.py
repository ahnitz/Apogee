# slangpy before numpy: numpy first breaks Vulkan device creation here.
import slangpy as spy
import numpy as np, time, pathlib

N, WG = 2048, 256
ND, NT = 8, 64
PAIRS = ND * NT

dev = spy.Device(type=spy.DeviceType.vulkan)
print("device:", dev.info.adapter_name)
mod = dev.load_module_from_source("mf", pathlib.Path("mf.slang").read_text())
def kern(name):
    return dev.create_compute_kernel(dev.link_program([mod], [mod.entry_point(name)]))
k_fused, k_corr, k_reduce = kern("fused"), kern("corr"), kern("reduce")

rng = np.random.default_rng(0)
d = (rng.standard_normal((ND, N)) + 1j*rng.standard_normal((ND, N))).astype(np.complex64)
h = (rng.standard_normal((NT, N)) + 1j*rng.standard_normal((NT, N))).astype(np.complex64)
h /= np.linalg.norm(h, axis=1, keepdims=True)
# bury a signal so the peak is a real peak, not a noise excursion
ramp = np.exp(-2j*np.pi*611*np.arange(N)/N)
d[3] += (9.0 * h[21] * ramp).astype(np.complex64)

def buf(arr, rw=False):
    return dev.create_buffer(
        element_count=arr.size, struct_size=8,
        usage=spy.BufferUsage.unordered_access if rw else spy.BufferUsage.shader_resource,
        data=np.ascontiguousarray(arr).view(np.float32))
bd, bh = buf(d), buf(h)
bcorr = dev.create_buffer(element_count=PAIRS*N, struct_size=8,
                          usage=spy.BufferUsage.unordered_access)
bmag = dev.create_buffer(element_count=PAIRS, struct_size=4,
                         usage=spy.BufferUsage.unordered_access)
bidx = dev.create_buffer(element_count=PAIRS, struct_size=4,
                         usage=spy.BufferUsage.unordered_access)

def run_fused():
    k_fused.dispatch(thread_count=[PAIRS*WG, 1, 1], data=bd, tmpl=bh,
                     peakMag=bmag, peakIdx=bidx, ntmpl=NT)
def run_unfused():
    k_corr.dispatch(thread_count=[PAIRS*WG, 1, 1], data=bd, tmpl=bh,
                    corrOut=bcorr, ntmpl=NT)
    k_reduce.dispatch(thread_count=[PAIRS*WG, 1, 1], corrIn=bcorr,
                      peakMag=bmag, peakIdx=bidx)

# ---- correctness against a float64 reference ----
run_fused(); dev.wait()
gmag = bmag.to_numpy().view(np.float32).reshape(ND, NT)
gidx = bidx.to_numpy().view(np.uint32).reshape(ND, NT)
ref = np.abs(np.fft.ifft(d[:, None, :] * np.conj(h)[None, :, :], axis=2) * N)
rmag, ridx = ref.max(axis=2), ref.argmax(axis=2)
rel = np.abs(gmag - rmag) / np.maximum(rmag, 1e-30)
print("peak magnitude: max rel err %.2e   median %.2e" % (rel.max(), np.median(rel)))
print("peak index    : %d of %d exact" % ((gidx == ridx).sum(), PAIRS))
print("injected pair (3,21): gpu lag %d snr %.3f | ref lag %d snr %.3f"
      % (gidx[3,21], gmag[3,21], ridx[3,21], rmag[3,21]))

def per(fn, floor=0.05):
    fn(); dev.wait()
    k = 1
    while True:
        t0 = time.perf_counter()
        for _ in range(k): fn()
        dev.wait()
        dt = time.perf_counter() - t0
        if dt >= floor: return dt / k
        k *= 2

tf = min(per(run_fused) for _ in range(5))
tu = min(per(run_unfused) for _ in range(5))
flops = PAIRS * (5.0*N*np.log2(N) + 6.0*N)
traffic_f = (ND + NT) * N * 8
traffic_u = traffic_f + PAIRS * N * 8 * 2
print("\n%-22s %9s %11s %12s" % ("", "ms", "GFLOP/s", "eff GB/s"))
print("%-22s %9.3f %11.0f %12.1f" % ("fused", tf*1e3, flops/tf/1e9, traffic_f/tf/1e9))
print("%-22s %9.3f %11.0f %12.1f" % ("corr + reduce", tu*1e3, flops/tu/1e9, traffic_u/tu/1e9))
print("%-22s %9.2fx" % ("fusion wins by", tu/tf))
