"""Where each register ends up in the output, and how that was established.

The four-step skips the final transposes, so the transform leaves its result
in mixed-radix digit-reversed order: register q of thread tid holds output
index reverse(tid*16 + q) under radices [16]*NLEVELS + INNER.

Nothing needed this until the kernel had to report an argmax and a per-bin
peak. A peak MAGNITUDE is order-independent, which is why every test passed
for as long as magnitude was all the kernel returned -- and why getting this
wrong would have been invisible rather than loud.

It was established by dumping every register against a float64 reference on
the GPU for all five lengths, then fitting. The
fit is exact, not approximate, for 1024 through 16384.
"""

#: Radices, most significant first. NLEVELS 16s for the exchange levels,
#: then the innermost block's own decomposition. Note INNER=4 contributes
#: [2, 2] and not [4]: dft4 leaves its pair bit-reversed. That is measured,
#: not reasoned -- [4] was tried and does not reproduce the hardware.
RADICES = {
    1024:  [16, 16, 2, 2],
    2048:  [16, 16, 8],
    4096:  [16, 16, 16],
    8192:  [16, 16, 16, 2],
    16384: [16, 16, 16, 2, 2],
}


def slot_to_index(slot, radices):
    """Mixed-radix digit reversal.

    Every radix is a power of two, so this is a bit shuffle, and the digits
    are produced least-significant first and consumed in that same order --
    which is why extraction and rebuild fuse into one loop with no array.
    The kernel needs that: dynamic indexing of a register array spills to
    scratch, and did crash a driver here once.
    """
    lg = [int(r).bit_length() - 1 for r in radices]
    idx, x = 0, slot
    for i in range(len(lg) - 1, -1, -1):
        d = x & ((1 << lg[i]) - 1)
        x >>= lg[i]
        idx = (idx << lg[i]) | d
    return idx


def permutation(n):
    """slot -> output index, for every slot."""
    rad = RADICES[n]
    return [slot_to_index(s, rad) for s in range(n)]


def bin_is_fixed_by_register(n, start, binsize):
    """Registers whose whole index range lies inside one bin.

    index = q*WG + reverse(tid), so register q spans [q*WG, (q+1)*WG). When
    that range sits inside a single bin, every thread's register q shares a
    bin and a wave-wide max can replace one atomic per lane -- which is the
    difference between 4.49 ms and 2.61 ms at n=4096.

    Returns the set of q for which that holds, so the caller can see that it
    degrades gracefully rather than requiring an aligned start or a
    power-of-two binsize.
    """
    wg = n // 16
    out = set()
    for q in range(16):
        lo, hi = q * wg, (q + 1) * wg - 1
        if (lo - start) // binsize == (hi - start) // binsize:
            out.add(q)
    return out
