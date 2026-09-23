"""Sweep the GPU back end's kernel shape, checking every configuration.

    python tools/metal_tune.py onepass            # values per thread x radix
    python tools/metal_tune.py fourstep           # split A x column tile W2
    python tools/metal_tune.py onepass --n 1024 4096 --reps 30

The defaults in metal/mf_metal.m came from these sweeps on an M2.  The shape
is read from the environment when the Metal device is first opened
(MF_METAL_VPT, MF_METAL_RADX, MF_METAL_LOGA, MF_METAL_W2, MF_METAL_TILE), so
every configuration runs in a fresh interpreter.  Each one is checked against
numpy before it is timed -- an invalid shape once looked like a 5x speedup
because it skipped every butterfly -- and a wrong one is reported, not timed.

Timings are GPU kernel time per pair (median), with enough pairs per run for
the GPU clocks to ramp: runs of a millisecond or so measure the power state as
much as the kernel.
"""
import argparse
import itertools
import os
import subprocess
import sys

CHILD = r"""
import sys, numpy as np
from matchedfilter import metal, _metal
out = []
for n in map(int, sys.argv[2:]):
    nd = 16
    nt = max(16, min(4096, (1 << 26) // (n * nd)))
    rng = np.random.default_rng(0)
    D = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    H = (rng.standard_normal((nt, n)) + 1j * rng.standard_normal((nt, n))).astype(np.complex64)
    try:
        f = metal.MatchedFilter(n, nd, nt)
    except Exception as e:
        out.append("%d:n/a(%s)" % (n, str(e).split(": ")[-1][:40])); continue
    f.set_data(D); f.set_templates(H)
    bs = n // 16
    pk = f.run(binsize=bs, threshold=0.0, data=(0, 2), templates=(0, 3))
    z = np.fft.ifft(D[:2, None].astype(np.complex128)
                    * np.conj(H[None, :3].astype(np.complex128)), axis=-1) * n
    a = np.abs(z).reshape(2, 3, 16, bs)
    ok = (np.array_equal(pk["index"], a.argmax(-1) + bs * np.arange(16))
          and np.allclose(pk["magnitude"], a.max(-1), rtol=1e-5))
    if not ok:
        out.append("%d:WRONG" % n); continue
    g = []
    for _ in range(int(sys.argv[1])):
        f.run(binsize=bs, threshold=1e30, raw=True)
        g.append(_metal.last_gpu_seconds())
    out.append("%d:%.3f" % (n, np.median(g[3:]) / (nd * nt) * 1e6))
print(" ".join(out))
"""

SWEEPS = {
    "onepass": dict(
        n=[256, 1024, 2048, 4096],
        grid=[("MF_METAL_VPT", "MF_METAL_RADX"),
              [(4, 4), (8, 4), (8, 8), (16, 8), (16, 16), (32, 16)]]),
    "fourstep": dict(
        n=[16384, 65536, 262144, 1 << 20],
        grid=[("MF_METAL_LOGA", "MF_METAL_W2"),
              list(itertools.product([4, 5, 6, 7, 8], [8, 16, 32, 64]))]),
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sweep", choices=sorted(SWEEPS))
    ap.add_argument("--n", type=int, nargs="+")
    ap.add_argument("--reps", type=int, default=15)
    a = ap.parse_args(argv)
    sw = SWEEPS[a.sweep]
    names, values = sw["grid"]
    sizes = [str(x) for x in (a.n or sw["n"])]
    print("us/pair (GPU kernel time), per n")
    for vals in values:
        env = dict(os.environ, **{k: str(v) for k, v in zip(names, vals)})
        r = subprocess.run([sys.executable, "-c", CHILD, str(a.reps)] + sizes,
                           env=env, capture_output=True, text=True)
        res = r.stdout.strip() or ("failed: " + r.stderr.strip().splitlines()[-1])
        label = " ".join("%s=%s" % (k.replace("MF_METAL_", ""), v) for k, v in zip(names, vals))
        print("%-22s %s" % (label, res), flush=True)


if __name__ == "__main__":
    main()
