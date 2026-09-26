#!/usr/bin/env python3
"""tierb.slang at register level, in Python, generalised in R.

gpu_decomposition.py checks the four-step MATHS.  This checks the thing
that actually ships: which register of which thread holds which output
index, through the real ``want[]`` scatter, the real chunked exchange and
the real ``slotToIndex`` digit reversal.

That mapping is the kernel's silent failure mode.  A peak MAGNITUDE is
order-independent, so an index or twiddle mistake here survives every
benchmark and every "does it run" test, and only shows up as a peak
attributed to the wrong sample.  Two such bugs have shipped in this file's
history; both would have been caught by running this first.

The model is faithful when it reproduces the five lengths already in the
kernel.  It does -- including INNER=4, where Slang's ``dft4`` leaves its
pair bit-reversed and the index mapping spends two radix-2 digits rather
than one radix-4 digit.  That quirk was measured, not reasoned, and this
file encodes it rather than rediscovering it.

Generalising R is what takes the kernel past n=16384.  A workgroup is
capped at 1024 threads and n = WG * R, so 16 points per thread stops
there; 32 and 64 reach 32768 and 65536.  Above that WG*R cannot cover n
at any R the register file will hold, and the length needs the four-step
split across dispatches -- a different kernel, not a wider one.

    n        R   WG     NLEVELS  INNER  per-level   innermost
    1024     16    64      2       4     dft16      4 x dft4
    2048     16   128      2       8     dft16      2 x dft8
    4096     16   256      2      16     dft16      1 x dft16
    8192     16   512      3       2     dft16      8 x dft2
    16384    16  1024      3       4     dft16      4 x dft4
    32768    32  1024      2      32     dft32      1 x dft32
    65536    64  1024      2      16     dft64      4 x dft16
"""
import numpy as np

PI = np.pi

#: Natural-order m-point inverse DFT.  The kernel's dft2/dft8/dft16 all
#: leave natural order; dft4 does not, and is special-cased at its one
#: call site rather than here.
def dftn(r, m):
    return np.fft.ifft(r) * m


#: The per-level radix.  R=32 and R=64 are built from dft16 the same way
#: the Slang is: a decimation-in-frequency split, twiddles, dft16 on each
#: sub-block, then an interleave that restores natural order.  Natural
#: order is not optional -- the want[] scatter below indexes registers by
#: frequency k2, so a permuted radix would mis-route the whole level.
def dftR(r, R):
    if R <= 16:
        return dftn(r, R)
    if R == 32:
        j = np.arange(16)
        u = r[:16] + r[16:]
        v = (r[:16] - r[16:]) * np.exp(2j * PI * j / 32)
        o = np.empty(32, complex)
        o[0::2] = dftn(u, 16)
        o[1::2] = dftn(v, 16)
        return o
    if R == 64:
        x = r.reshape(4, 16)
        j = np.arange(16)
        o = np.empty(64, complex)
        for p in range(4):
            t = sum(x[q] * np.exp(2j * PI * p * q / 4) for q in range(4))
            o[p::4] = dftn(t * np.exp(2j * PI * p * j / 64), 16)
        return o
    raise ValueError("no in-register DFT at R=%d" % R)


#: WG, NLEVELS and INNER as the Slang computes them -- recurse TB /= R
#: until a whole block fits in one thread's registers.
def geom(n, R):
    WG = n // R
    levels, t = 0, WG
    while t > R:
        t //= R
        levels += 1
    levels += 1
    return WG, levels, WG // R ** (levels - 1)


def innermost(r, INNER, R):
    o = r.copy()
    for b in range(R // INNER):
        blk = dftn(r[b * INNER:(b + 1) * INNER], INNER)
        if INNER == 4:
            blk = blk[[0, 2, 1, 3]]      # Slang dft4 leaves its pair reversed
        o[b * INNER:(b + 1) * INNER] = blk
    return o


#: The mixed-radix digit reversal, mirroring slotToIndex/lgOf/LGI0/NDIG.
def slot_to_index(slot, NLEVELS, INNER, lgR):
    NIDIG = 2 if INNER == 4 else 1
    LGI0 = {2: 1, 4: 1, 8: 3, 16: 4, 32: 5, 64: 6}[INNER]
    idx, x = 0, slot
    for i in range(NLEVELS + NIDIG - 1, -1, -1):
        lg = lgR if i < NLEVELS else (LGI0 if i == NLEVELS else 1)
        d = x & ((1 << lg) - 1)
        x >>= lg
        idx = (idx << lg) | d
    return idx


def registers(x, n, R):
    """The transform, returning reg[tid][q] -- what each thread holds.

    Split out from run() because Tier C calls it twice: a length past
    65536 is two of these with a twiddle and a transpose between, and the
    sub-transform's register-to-index mapping is the contract the two
    stages meet on. See gpu_tierc_model.py.
    """
    WG, NLEVELS, INNER = geom(n, R)
    lgR = int(np.log2(R))

    reg = np.zeros((WG, R), complex)
    for tid in range(WG):                       # level-0 stride-WG gather
        for q in range(R):
            reg[tid][q] = x[tid + WG * q]

    for lvl in range(NLEVELS):
        TB = WG >> (lgR * lvl)
        ln = n >> (lgR * lvl)
        lgTB = TB.bit_length() - 1
        staged = np.zeros_like(reg)
        for tid in range(WG):
            lane = tid & (TB - 1)
            staged[tid] = dftR(reg[tid], R) * np.exp(2j * PI * lane * np.arange(R) / ln)

        #: The exchange, as the virtual array it scatters through.  The
        #: kernel stages it in R/CH chunks through LDS and inverts the
        #: formula per reader; the addressing is identical.
        V = np.zeros(n, complex)
        for tid in range(WG):
            blk, lane = tid >> lgTB, tid & (TB - 1)
            for i in range(R):
                V[blk * ln + i * TB + lane] = staged[tid][i]

        per, TB2 = R // max(TB, 1), max(TB >> lgR, 1)
        out = np.zeros_like(reg)
        for tid in range(WG):
            blk, lane = tid >> lgTB, tid & (TB - 1)
            blk2, lane2 = tid // TB2, tid % TB2
            for d in range(R):
                j, m = d // max(TB, 1), d % max(TB, 1)
                want = (blk * ln + (lane * per + j) * TB + m) if TB <= R \
                    else (blk2 * TB + lane2 + TB2 * d)
                out[tid][d] = V[want]
        reg = out

    for tid in range(WG):
        reg[tid] = innermost(reg[tid], INNER, R)
    return reg


def run(n, R, rng):
    """Return (geometry, relative error) for one length."""
    WG, NLEVELS, INNER = geom(n, R)
    lgR = int(np.log2(R))
    x = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    reg = registers(x, n, R)

    ref = np.fft.ifft(x) * n
    err = max(abs(reg[tid][q] - ref[slot_to_index(tid * R + q, NLEVELS, INNER, lgR)])
              for tid in range(WG) for q in range(R))
    return (WG, NLEVELS, INNER), err / np.abs(ref).max()


#: Every length the kernel builds, with the R it is built at.
CASES = ((64, 16), (128, 16), (256, 16), (512, 16),
         (1024, 16), (2048, 16), (4096, 16), (8192, 16), (16384, 16),
         (32768, 32), (65536, 64))


if __name__ == "__main__":
    rng = np.random.default_rng(7)
    print("%-8s %-3s %-6s %-8s %-6s %-9s" %
          ("n", "R", "WG", "NLEVELS", "INNER", "rel err"))
    bad = 0
    for n, R in CASES:
        (WG, NL, INNER), err = run(n, R, rng)
        ok = err < 1e-11
        bad += not ok
        print("%-8d %-3d %-6d %-8d %-6d %-9.1e %s" %
              (n, R, WG, NL, INNER, err, "OK" if ok else "WRONG"))
    raise SystemExit(1 if bad else 0)
