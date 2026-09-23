"""What does AMD's own tuned FFT achieve on this device?

Without a reference, "15% of FMA peak" says nothing: an FFT is not
FMA-dense. rocFFT is the honest yardstick.
"""
import ctypes, time, numpy as np

hip = ctypes.CDLL("libamdhip64.so.6", mode=ctypes.RTLD_GLOBAL)
roc = ctypes.CDLL("librocfft.so.0", mode=ctypes.RTLD_GLOBAL)

N, BATCH = 1024, 512
nbytes = N * BATCH * 8                      # complex64

def chk(r, what):
    if r != 0: raise RuntimeError("%s -> %d" % (what, r))

chk(roc.rocfft_setup(), "rocfft_setup")
dbuf = ctypes.c_void_p()
chk(hip.hipMalloc(ctypes.byref(dbuf), ctypes.c_size_t(nbytes)), "hipMalloc")

host = (np.random.default_rng(0).standard_normal((BATCH, N))
        + 1j*np.random.default_rng(1).standard_normal((BATCH, N))).astype(np.complex64)
chk(hip.hipMemcpy(dbuf, host.ctypes.data_as(ctypes.c_void_p),
                  ctypes.c_size_t(nbytes), ctypes.c_int(1)), "hipMemcpy H2D")

plan = ctypes.c_void_p()
lengths = (ctypes.c_size_t * 1)(N)
chk(roc.rocfft_plan_create(ctypes.byref(plan),
                           ctypes.c_int(0),       # inplace
                           ctypes.c_int(1),       # complex inverse
                           ctypes.c_int(0),       # single precision
                           ctypes.c_size_t(1),    # 1-D
                           lengths,
                           ctypes.c_size_t(BATCH),
                           None), "rocfft_plan_create")

bufs = (ctypes.c_void_p * 1)(dbuf)
def run():
    roc.rocfft_execute(plan, bufs, None, None)

run(); hip.hipDeviceSynchronize()
best = 1e9
for _ in range(7):
    t0 = time.perf_counter()
    for _ in range(50): run()
    hip.hipDeviceSynchronize()
    best = min(best, (time.perf_counter() - t0) / 50)

flops = BATCH * 5.0 * N * np.log2(N)
print("rocFFT, %d inverse transforms of length %d" % (BATCH, N))
print("  %.4f ms   %.0f GFLOP/s   (transform only, no multiply, no peak scan)"
      % (best*1e3, flops/best/1e9))
roc.rocfft_plan_destroy(plan); roc.rocfft_cleanup()
