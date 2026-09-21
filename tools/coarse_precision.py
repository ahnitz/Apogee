#!/usr/bin/env python3
"""What does a narrower coarse pass cost the gate statistic?

The coarse pass only has to decide whether something loud is present, so its
arithmetic can be much cruder than the reconstruction's.  This measures how
much cruder, on a captured pycbc call rather than on synthetic data:
quantise the product spectrum and round every butterfly output to the same
grid, with block floating point at each stage as a fixed-point FFT does.

    python tools/coarse_precision.py work/fixtures/hier-00.npz
"""
import sys
import numpy as np


def fft_rounded(x, bits):
    """Radix-2 DIT with every stage rounded to `bits`, block floating point."""
    N = len(x)
    x = x.copy()
    j = 0
    for i in range(1, N):
        b = N >> 1
        while j & b:
            j ^= b
            b >>= 1
        j |= b
        if i < j:
            x[i], x[j] = x[j], x[i]

    def q(v):
        if bits is None:
            return v
        s = np.abs(v).max()
        if s == 0:
            return v
        sc = ((1 << (bits - 1)) - 1) / s
        return (np.round(v.real * sc) + 1j * np.round(v.imag * sc)) / sc

    step = 2
    while step <= N:
        w = np.exp(-2j * np.pi * np.arange(step // 2) / step).astype(np.complex64)
        if bits:
            w = q(w)
        for k in range(0, N, step):
            a = x[k:k + step // 2]
            b = x[k + step // 2:k + step] * w
            x[k:k + step // 2] = a + b
            x[k + step // 2:k + step] = a - b
        x = q(x)
        step <<= 1
    return x


def main(path, nblocks=10, ntmpl=6):
    z = np.load(path)
    n, m = int(z["n_fft"]), int(z["band"])
    series, H, st = z["series"], z["templates"], z["starts"]
    rng = np.random.default_rng(0)
    blocks = rng.choice(len(st), nblocks, replace=False)
    tm = rng.choice(len(H), ntmpl, replace=False)

    out = {}
    for bits, label in ((None, "float32"), (16, "int16"), (12, "int12"),
                        (11, "fp16 mantissa")):
        r = []
        for b in blocks:
            blk = np.zeros(n, np.complex64)
            s0 = int(st[b])
            have = min(n, max(0, len(series) - s0))
            blk[:have] = series[s0:s0 + have]
            D = np.fft.fft(blk) / n
            for t in tm:
                prod = (D * H[t]).astype(np.complex64)[:m]
                ref = np.abs(np.fft.ifft(prod)).max() * m
                got = np.abs(fft_rounded(prod, bits)).max()
                r.append(got / ref if ref > 0 else 1.0)
        out[label] = np.array(r)

    base = out["float32"]
    print("%d pairs from %s, band %d" % (len(base), path.split("/")[-1], m))
    print("%-16s %10s %10s %10s" % ("arithmetic", "median", "1st pct", "worst"))
    for label, r in out.items():
        rel = r / base
        print("%-16s %9.4f %10.4f %10.4f"
              % (label, np.median(rel), np.percentile(rel, 1), rel.min()))
    print("\nA statistic that reads low by x needs the gate lowered by x;\n"
          "the gate currently carries 6% of margin for calibration.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         "/home/ahnitz/projects/claude/searchdev/work/fixtures/hier-00.npz")
