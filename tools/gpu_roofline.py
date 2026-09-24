#!/usr/bin/env python3
"""What this GPU can do, and what fraction of it the filter reaches.

"Faster than last week" is not a target. This measures the two ceilings
that bound the kernel -- arithmetic throughput and memory bandwidth -- on
the device in front of you, then states the filter as a fraction of
whichever one binds. Spec sheets are not used: a clock and a core count
tell you what the silicon could do, not what a dispatch achieves.

The arithmetic probe runs eight independent FMA chains per thread so the
pipeline stays full without the compiler collapsing them; the bandwidth
probe streams float4 and is checked against the read+write it claims.
"""
import ctypes
import sys
import time

import numpy as np

# The installed package first: putting the source tree ahead of it hides
# the compiled _core that an editable install keeps elsewhere.
try:
    from matchedfilter import _mtlcompute as M
except ImportError:
    sys.path.insert(0, __file__.rsplit("/", 2)[0] + "/python")
    from matchedfilter import _mtlcompute as M      # noqa: E402

#: Chains per thread. Eight was not enough to saturate: sixteen measures
#: higher, which means eight was reporting FMA latency rather than
#: throughput. The probe reports the best of several widths so the number
#: is a ceiling and not an artefact of one choice.
CHAINS = (4, 8, 16, 32)

ADD = """
#include <metal_stdlib>
using namespace metal;
[[kernel]] void probe(device float* out [[buffer(0)]],
                      constant uint& iters [[buffer(1)]],
                      uint gid [[thread_position_in_grid]]) {
    float a0=gid, a1=gid+1, a2=gid+2, a3=gid+3;
    float a4=gid+4, a5=gid+5, a6=gid+6, a7=gid+7;
    float a8=gid+8, a9=gid+9, aA=gid+10, aB=gid+11;
    float aC=gid+12, aD=gid+13, aE=gid+14, aF=gid+15;
    const float c = 1.0000001f;
    for (uint i = 0; i < iters; ++i) {
        a0+=c; a1+=c; a2+=c; a3+=c; a4+=c; a5+=c; a6+=c; a7+=c;
        a8+=c; a9+=c; aA+=c; aB+=c; aC+=c; aD+=c; aE+=c; aF+=c;
    }
    out[gid] = a0+a1+a2+a3+a4+a5+a6+a7+a8+a9+aA+aB+aC+aD+aE+aF;
}
"""

FMA16 = """
#include <metal_stdlib>
using namespace metal;
[[kernel]] void probe(device float* out [[buffer(0)]],
                      constant uint& iters [[buffer(1)]],
                      uint gid [[thread_position_in_grid]]) {
    float a0=gid, a1=gid+1, a2=gid+2, a3=gid+3;
    float a4=gid+4, a5=gid+5, a6=gid+6, a7=gid+7;
    float a8=gid+8, a9=gid+9, aA=gid+10, aB=gid+11;
    float aC=gid+12, aD=gid+13, aE=gid+14, aF=gid+15;
    const float k = 1.0000001f, c = 0.0000001f;
    for (uint i = 0; i < iters; ++i) {
        a0=fma(a0,k,c); a1=fma(a1,k,c); a2=fma(a2,k,c); a3=fma(a3,k,c);
        a4=fma(a4,k,c); a5=fma(a5,k,c); a6=fma(a6,k,c); a7=fma(a7,k,c);
        a8=fma(a8,k,c); a9=fma(a9,k,c); aA=fma(aA,k,c); aB=fma(aB,k,c);
        aC=fma(aC,k,c); aD=fma(aD,k,c); aE=fma(aE,k,c); aF=fma(aF,k,c);
    }
    out[gid] = a0+a1+a2+a3+a4+a5+a6+a7+a8+a9+aA+aB+aC+aD+aE+aF;
}
"""

FMA = """
#include <metal_stdlib>
using namespace metal;
[[kernel]] void probe(device float* out [[buffer(0)]],
                      constant uint& iters [[buffer(1)]],
                      uint gid [[thread_position_in_grid]]) {
    float a0=gid, a1=gid+1, a2=gid+2, a3=gid+3;
    float a4=gid+4, a5=gid+5, a6=gid+6, a7=gid+7;
    const float k = 1.0000001f, c = 0.0000001f;
    for (uint i = 0; i < iters; ++i) {
        a0 = fma(a0,k,c); a1 = fma(a1,k,c); a2 = fma(a2,k,c); a3 = fma(a3,k,c);
        a4 = fma(a4,k,c); a5 = fma(a5,k,c); a6 = fma(a6,k,c); a7 = fma(a7,k,c);
    }
    // Consume, so nothing is dead code, without a store per iteration.
    out[gid] = a0+a1+a2+a3+a4+a5+a6+a7;
}
"""

COPY = """
#include <metal_stdlib>
using namespace metal;
[[kernel]] void probe(device const float4* src [[buffer(0)]],
                      device float4* dst [[buffer(1)]],
                      uint gid [[thread_position_in_grid]]) {
    dst[gid] = src[gid];
}
"""


class Probe:
    def __init__(self):
        self.ctx = M.Context(0)
        self.o = self.ctx.o

    def pipeline(self, src):
        err = ctypes.c_void_p()
        lib = self.o.call(self.ctx.device, b"newLibraryWithSource:options:error:",
                          args=(self.o.nsstring(src), None, ctypes.byref(err)),
                          argtypes=(ctypes.c_void_p,) * 3)
        if not lib:
            raise RuntimeError(M.describe_error(self.o, err))
        fn = self.o.call(lib, b"newFunctionWithName:",
                         args=(self.o.nsstring("probe"),),
                         argtypes=(ctypes.c_void_p,))
        err = ctypes.c_void_p()
        pso = self.o.call(self.ctx.device,
                          b"newComputePipelineStateWithFunction:error:",
                          args=(fn, ctypes.byref(err)),
                          argtypes=(ctypes.c_void_p, ctypes.c_void_p))
        if not pso:
            raise RuntimeError(M.describe_error(self.o, err))
        return pso

    def run(self, pso, groups, threads, buffers, reps=20):
        def once():
            cmd = self.o.call(self.ctx.queue, b"commandBuffer")
            enc = self.o.call(cmd, b"computeCommandEncoder")
            self.o.call(enc, b"setComputePipelineState:", restype=None,
                        args=(pso,), argtypes=(ctypes.c_void_p,))
            for i, b in enumerate(buffers):
                if isinstance(b, M._Buffer):
                    self.o.call(enc, b"setBuffer:offset:atIndex:", restype=None,
                                args=(b.handle, 0, i),
                                argtypes=(ctypes.c_void_p,) * 1 + (ctypes.c_ulong,) * 2)
                else:
                    v = ctypes.c_uint32(b)
                    self.o.call(enc, b"setBytes:length:atIndex:", restype=None,
                                args=(ctypes.byref(v), 4, i),
                                argtypes=(ctypes.c_void_p, ctypes.c_ulong,
                                          ctypes.c_ulong))
            self.o.call(enc, b"dispatchThreadgroups:threadsPerThreadgroup:",
                        restype=None,
                        args=(M._MTLSize(groups, 1, 1), M._MTLSize(threads, 1, 1)),
                        argtypes=(M._MTLSize, M._MTLSize))
            self.o.call(enc, b"endEncoding", restype=None)
            self.o.call(cmd, b"commit", restype=None)
            self.o.call(cmd, b"waitUntilCompleted", restype=None)
        once(); once()
        best = float("inf")
        for _ in range(reps):
            t0 = time.perf_counter(); once()
            best = min(best, time.perf_counter() - t0)
        return best


def chain_src(nchain, op):
    """A probe with `nchain` independent dependency chains.

    Too few chains and the loop measures instruction LATENCY, not throughput:
    each operation waits on the previous one. Too many and the registers
    spill. The only way to know which side you are on is to sweep until the
    rate stops rising -- a single hardcoded width reports whatever it happens
    to hit and calls it the ceiling. 8 chains said 1322 GFLOP/s here and 16
    said 1482, which is precisely how that mistake looks from the inside.
    """
    decl = " ".join("float a%d=gid+%d;" % (i, i) for i in range(nchain))
    if op == "fma":
        body = " ".join("a%d=fma(a%d,k,c);" % (i, i) for i in range(nchain))
    else:
        body = " ".join("a%d+=c;" % i for i in range(nchain))
    tot = "+".join("a%d" % i for i in range(nchain))
    return """
#include <metal_stdlib>
using namespace metal;
[[kernel]] void probe(device float* out [[buffer(0)]],
                      constant uint& iters [[buffer(1)]],
                      uint gid [[thread_position_in_grid]]) {
    %s
    const float k = 1.0000001f, c = 0.0000001f;
    for (uint i = 0; i < iters; ++i) { %s }
    out[gid] = %s;
}
""" % (decl, body, tot)


def sweep(p, out, groups, threads, iters, op, widths):
    """Rate against chain width, so the plateau is visible rather than assumed."""
    lanes = threads * groups * iters
    per = 2 if op == "fma" else 1
    best, rows = 0.0, []
    for w in widths:
        # A pipeline that cannot hold the requested threads does not
        # fail the dispatch, it returns instantly and reports a rate in
        # the terapoints -- 6.3e12 GFLOP/s at 1024 threads and 64
        # chains, which is not a measurement.
        try:
            t = p.run(p.pipeline(chain_src(w, op)), groups, threads, [out, iters])
        except Exception as e:
            rows.append((w, None)); continue
        r = lanes * w * per / t
        if r > 1e13:            # no consumer GPU does 10 TFLOP/s of this
            rows.append((w, None)); continue
        rows.append((w, r))
        best = max(best, r)
    return best, rows


def main():
    p = Probe()
    print("device: %s" % p.ctx.name)
    print("  maxThreadgroupMemoryLength %d KB" % (p.ctx.max_shared_memory // 1024))

    threads, groups, iters = 256, 2048, 4096
    out = M._Buffer(p.ctx, threads * groups * 4)

    widths = (4, 8, 16, 24, 32, 48)
    fma, frows = sweep(p, out, groups, threads, iters, "fma", widths)
    add, arows = sweep(p, out, groups, threads, iters, "add", widths)
    print("  chains:   " + "".join("%8d" % w for w, _ in frows))
    print("  FMA     : " + "".join("%8.0f" % (r / 1e9) if r else "       -"
                                   for _, r in frows) + "  GFLOP/s")
    print("  add     : " + "".join("%8.0f" % (r / 1e9) if r else "       -"
                                   for _, r in arows) + "  GFLOP/s")
    print("  FP32 FMA peak        %8.2f GFLOP/s" % (fma / 1e9))


    # The rate that actually bounds an FFT. A radix butterfly is adds and
    # subtracts with a twiddle multiply, not a stream of FMAs, so quoting
    # the FMA peak as the denominator flatters the kernel by about 2x.
    print("  FP32 add (no FMA)    %8.2f GFLOP/s   <- the FFT-relevant one"
          % (add / 1e9))

    nfloat4 = 1 << 22                                  # 64 MB in, 64 MB out
    src = M._Buffer(p.ctx, nfloat4 * 16)
    dst = M._Buffer(p.ctx, nfloat4 * 16)
    t = p.run(p.pipeline(COPY), nfloat4 // 256, 256, [src, dst])
    moved = nfloat4 * 16 * 2
    print("  copy bandwidth       %8.2f GB/s      (%.3f ms, %d MB moved)"
          % (moved / t / 1e9, t * 1e3, moved // (1 << 20)))
    bw = moved / t
    p.ctx.destroy()
    filter_against(fma, add, bw)
    return fma, add, bw


def flops_per_pair(n):
    """Algorithmic float operations for one (data, template) pair.

    The inverse transform dominates; the other two terms are named because
    they are not negligible at these lengths and quietly dropping them
    would flatter the achieved rate by about 15%.
    """
    import math
    product = 6 * n                       # data * conj(template), complex
    inverse = 5 * n * math.log2(n)        # the transform
    peak = 3 * n                          # |z|^2 and the running max
    return product + inverse + peak


def filter_against(fma, add, bw):
    """The filter as a fraction of the ceilings just measured."""
    import time
    import numpy as np
    import matchedfilter as mf

    print()
    print("  the filter against those ceilings, whole run() call:")
    print("    %6s %7s %11s %10s %9s %9s"
          % ("n", "pairs", "us/pair", "GFLOP/s", "of add", "of DRAM"))
    for n in (1024, 2048, 4096, 8192, 16384):
        nd, nt = 16, 256
        pairs = nd * nt
        rng = np.random.default_rng(n)
        d = (rng.standard_normal((nd, n))
             + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
        h = (rng.standard_normal((nt, n))
             + 1j * rng.standard_normal((nt, n))).astype(np.complex64)
        try:
            f = mf.MatchedFilter(n, nd, nt, device="gpu")
            f.set_data(d)
            f.set_templates(h)
            f.run(binsize=n, threshold=5.5)
            for _ in range(2):
                f.run(binsize=n, threshold=5.5)
            t0 = time.perf_counter()
            for _ in range(8):
                f.run(binsize=n, threshold=5.5)
            per = (time.perf_counter() - t0) / 8 / pairs
            f._gpu.destroy()
        except Exception as e:
            print("    %6d %7d   %s" % (n, pairs, str(e)[:48]))
            continue
        got = flops_per_pair(n) / per
        # Templates and data are each read once per call from DRAM; the
        # batch is what makes the reuse, so this is (nd + nt) rows.
        dram = (nd + nt) * n * 8 / (per * pairs)
        print("    %6d %7d %9.4f us %10.1f %8.1f%% %8.1f%%"
              % (n, pairs, per * 1e6, got / 1e9, 100 * got / add,
                 100 * dram / bw))
    print()
    print("  'of add' is the fraction of the measured no-FMA rate, which is")
    print("  the one a transform is bounded by: its butterflies are adds and")
    print("  subtracts, and quoting the FMA peak would halve the number for")
    print("  free. 'of DRAM' says whether bandwidth is even in the picture.")


if __name__ == "__main__":
    main()
