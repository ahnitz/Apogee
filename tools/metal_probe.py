"""What this Metal device can actually do, and why a pipeline was refused.

`newComputePipelineStateWithFunction:` reports "Compilation failed" for any
back-end rejection, which names the failure without saying what it was. The
development machine has no Apple hardware, so the only way to tell the
candidate causes apart is to ask the device directly, in CI.

Three minimal kernels do the separating. They are deliberately trivial, so a
failure is about the FEATURE and not about anything in our own kernel:

  plain       arithmetic only -- if this fails, nothing will
  simd        simd_max / simd_is_first, which the reduction depends on
  threadgroup a 16 KB threadgroup array, the size n=4096 stages

Then every shipped kernel is asked for a pipeline and the full NSError is
printed for the ones refused.
"""
import ctypes
import pathlib
import sys

# The installed package first: an editable install may keep the compiled
# _core somewhere only its own import hook knows about, and putting the
# source tree on the path ahead of it hides that and fails on _core.
try:
    from matchedfilter import _mtlcompute as M
except ImportError:
    sys.path.insert(0,
                    str(pathlib.Path(__file__).resolve().parents[1] / "python"))
    from matchedfilter import _mtlcompute as M      # noqa: E402

PROBES = {
    "plain": """
#include <metal_stdlib>
using namespace metal;
[[kernel]] void probe(device uint* out [[buffer(0)]],
                      uint tid [[thread_position_in_threadgroup]]) {
    out[tid] = tid * 3u;
}
""",
    "simd": """
#include <metal_stdlib>
using namespace metal;
[[kernel]] void probe(device uint* out [[buffer(0)]],
                      uint tid [[thread_position_in_threadgroup]]) {
    uint m = simd_max(tid);
    if (simd_is_first()) { out[tid] = m; }
}
""",
    "threadgroup": """
#include <metal_stdlib>
using namespace metal;
[[kernel]] void probe(device uint* out [[buffer(0)]],
                      uint tid [[thread_position_in_threadgroup]]) {
    threadgroup uint scratch[4096];
    scratch[tid] = tid;
    threadgroup_barrier(mem_flags::mem_threadgroup);
    out[tid] = scratch[(tid + 1u) & 4095u];
}
""",
    "atomic_threadgroup": """
#include <metal_stdlib>
using namespace metal;
[[kernel]] void probe(device uint* out [[buffer(0)]],
                      uint tid [[thread_position_in_threadgroup]]) {
    threadgroup uint scratch[64];
    scratch[tid & 63u] = 0u;
    threadgroup_barrier(mem_flags::mem_threadgroup);
    atomic_fetch_max_explicit((threadgroup atomic_uint*)&scratch[tid & 63u],
                              tid, memory_order_relaxed);
    threadgroup_barrier(mem_flags::mem_threadgroup);
    out[tid] = scratch[tid & 63u];
}
""",
}

#: MTLGPUFamily. Apple7 is M1; Metal3 gates the newer shading language.
FAMILIES = [("Apple" + str(i), 1000 + i) for i in range(1, 10)]
FAMILIES += [("Mac2", 2002), ("Common1", 3001), ("Common3", 3003),
             ("Metal3", 5001)]


ISOLATION = """A failed pipeline WEDGES this driver, so each kernel runs alone.

Measured on the Apple Paravirtual device: after the second over-limit
kernel, every later pipeline creation failed regardless of content --
including kernels the suite then ran correctly in a fresh process. Checking
them in one process therefore reports a cascade of failures that are not
real, and the order they happen to be checked in decides which ones look
broken. Each stem gets its own process so one genuine failure cannot
manufacture ten false ones."""


def main():
    o = M._ObjC()
    devices = []
    o.metal.MTLCopyAllDevices.restype = ctypes.c_void_p
    arr = o.metal.MTLCopyAllDevices()
    n = int(o.call(arr, b"count", restype=ctypes.c_ulong)) if arr else 0
    for i in range(n):
        devices.append(o.call(arr, b"objectAtIndex:", args=(i,),
                              argtypes=(ctypes.c_ulong,)))
    if not devices:
        print("no Metal device")
        return 1

    bad = 0
    # With no argument: the device and the four minimal kernels only. A
    # shipped kernel is checked only when named, one per process -- see
    # ISOLATION.
    stems = [pathlib.Path(sys.argv[1])] if len(sys.argv) > 1 else []
    for dev in devices:
        name = o.to_str(o.call(dev, b"name"))
        print("=== %s ===" % name)
        tg = int(o.call(dev, b"maxThreadgroupMemoryLength",
                        restype=ctypes.c_ulong))
        print("  maxThreadgroupMemoryLength %d bytes (%d KB)" % (tg, tg // 1024))
        got = [f for f, v in FAMILIES
               if o.call(dev, b"supportsFamily:", restype=ctypes.c_bool,
                         args=(v,), argtypes=(ctypes.c_long,))]
        print("  families: %s" % (", ".join(got) or "none reported"))

        for label, src in PROBES.items():
            err = ctypes.c_void_p()
            lib = o.call(dev, b"newLibraryWithSource:options:error:",
                         args=(o.nsstring(src), None, ctypes.byref(err)),
                         argtypes=(ctypes.c_void_p,) * 3)
            if not lib:
                print("  probe %-18s SOURCE FAILED  %s"
                      % (label, M.describe_error(o, err)))
                bad += 1
                continue
            fn = o.call(lib, b"newFunctionWithName:",
                        args=(o.nsstring("probe"),),
                        argtypes=(ctypes.c_void_p,))
            err = ctypes.c_void_p()
            pso = o.call(dev, b"newComputePipelineStateWithFunction:error:",
                         args=(fn, ctypes.byref(err)),
                         argtypes=(ctypes.c_void_p, ctypes.c_void_p))
            if not pso:
                print("  probe %-18s PIPELINE FAILED  %s"
                      % (label, M.describe_error(o, err)))
                bad += 1
            else:
                lim = int(o.call(pso, b"maxTotalThreadsPerThreadgroup",
                                 restype=ctypes.c_ulong))
                print("  probe %-18s ok (max %d threads/group)" % (label, lim))

        for lib_path in stems:
            stem = lib_path.stem
            entry = "gatedTierB" if stem.startswith("gated") else "fusedTierB"
            err = ctypes.c_void_p()
            url = o.call(o.objc.objc_getClass(b"NSURL"), b"fileURLWithPath:",
                         args=(o.nsstring(str(lib_path)),),
                         argtypes=(ctypes.c_void_p,))
            lib = o.call(dev, b"newLibraryWithURL:error:",
                         args=(url, ctypes.byref(err)),
                         argtypes=(ctypes.c_void_p, ctypes.c_void_p))
            if not lib:
                print("  %-22s LIBRARY FAILED  %s"
                      % (stem, M.describe_error(o, err)))
                bad += 1
                continue
            fn = o.call(lib, b"newFunctionWithName:",
                        args=(o.nsstring(entry),),
                        argtypes=(ctypes.c_void_p,))
            if not fn:
                print("  %-22s no entry %s" % (stem, entry))
                bad += 1
                continue
            err = ctypes.c_void_p()
            pso = o.call(dev, b"newComputePipelineStateWithFunction:error:",
                         args=(fn, ctypes.byref(err)),
                         argtypes=(ctypes.c_void_p, ctypes.c_void_p))
            if not pso:
                print("  %-22s PIPELINE FAILED  %s"
                      % (stem, M.describe_error(o, err)))
                bad += 1
            else:
                lim = int(o.call(pso, b"maxTotalThreadsPerThreadgroup",
                                 restype=ctypes.c_ulong))
                used = int(o.call(pso, b"staticThreadgroupMemoryLength",
                                  restype=ctypes.c_ulong))
                print("  %-22s ok (max %d threads, %d B threadgroup)"
                      % (stem, lim, used))
    print("\n%d probe(s) failed" % bad)
    return 0                    # diagnostic only: never fail the job


if __name__ == "__main__":
    raise SystemExit(main())
