#!/usr/bin/env python3
"""How accurate is a fixed-point coarse pass, on real captured pairs?

The even coarse pass is 72% of the hierarchical filter's cost and already
runs at the arithmetic its transform size implies, so the only way to make it
cheaper is to do it in fewer bits.  What matters is NOT that the fixed-point
maximum be accurate -- it is that its error be BOUNDED.  With a bound eps, the
pass stays exact:

    fixed*(1+eps) <  gate   ->  reject, no float transform
    fixed*(1-eps) >= gate   ->  fire
    otherwise                   run the float pass as today

so the question this answers is how wide that undecided band is.  A pass that
is twice as fast but leaves half the pairs undecided is worth nothing.

Model A quantises only the input product and transforms exactly: it isolates
input quantisation, and is a FLOOR on the error of any fixed-point pipeline.
If A is already too wide there is no point writing the kernel.
"""
import glob
import numpy as np

def pairs(nblk=6, stride=2, nfiles=4):
    out = []
    for path in sorted(glob.glob(
            "/home/ahnitz/projects/claude/searchdev/work/fixtures/hier-*.npz"))[:nfiles]:
        z = np.load(path)
        n, m = int(z["n_fft"]), int(z["band"])
        series, H = z["series"], z["templates"]
        st, ws, we = z["starts"], z["win_start"], z["win_end"]
        rng = np.random.default_rng(7)
        for bi in rng.choice(len(st), nblk, replace=False):
            blk = np.zeros(n, np.complex64); s0 = int(st[bi])
            have = min(n, max(0, len(series) - s0))
            blk[:have] = series[s0:s0 + have]
            D = (np.fft.fft(blk) / n).astype(np.complex128)
            r = n // m
            lo = max(0, int(ws[bi]) // r - 1); hi = min(m, (int(we[bi]) + r - 1) // r)
            for t in range(0, len(H), stride):
                out.append((D * H[t])[:m], )
                out[-1] = ((D * H[t])[:m], lo, hi)
    return out

def qerr(P, lo, hi, bits, group):
    """Quantise P to `bits` with a shared exponent over each `group` bins,
    then transform exactly.  group=m is one exponent for the whole vector."""
    m = len(P)
    top = float(2 ** (bits - 1) - 1)
    Q = np.empty_like(P)
    for a in range(0, m, group):
        b = P[a:a + group]
        s = max(np.abs(b.real).max(), np.abs(b.imag).max())
        if s == 0: Q[a:a + group] = 0; continue
        q = s / top
        Q[a:a + group] = (np.round(b.real / q) + 1j * np.round(b.imag / q)) * q
    yt = np.abs(np.fft.ifft(P) * m)[lo:hi].max()
    yq = np.abs(np.fft.ifft(Q) * m)[lo:hi].max()
    return yq / yt

if __name__ == "__main__":
    P = pairs()
    print("%d real pairs, m=%d\n" % (len(P), len(P[0][0])))
    print("  bits  group      median      worst low     worst high    band")
    for bits in (16, 12, 8):
        for group in (len(P[0][0]), 64, 16):
            r = np.array([qerr(p, lo, hi, bits, group) for p, lo, hi in P])
            band = r.max() / r.min()
            print("  %4d  %5s   %9.6f      %9.6f      %9.6f   %6.3fx" %
                  (bits, "all" if group == len(P[0][0]) else group,
                   np.median(r), r.min(), r.max(), band))


# ---------------------------------------------------------------- model B
# A real fixed-point pipeline: int16 storage between stages, int32 inside the
# butterfly, int16 twiddles, and a shared exponent renormalised per stage.
# This is where the precision actually goes -- a radix-2 stage can grow the
# vector by 2, so ten of them can grow it by 1024, and every doubling that is
# scaled away is a bit lost.  For random-phase data growth is nearer sqrt(2) a
# stage, so the loss should be ~5 bits and not ~10, but that is a claim about
# real data and this measures it on real data.

def _bitrev(m):
    b = np.arange(m); r = np.zeros(m, np.int64); k = m.bit_length() - 1
    for i in range(k): r |= ((b >> i) & 1) << (k - 1 - i)
    return r

def fixed_ifft(re, im, bits=16, tw_bits=15):
    """Inverse transform of int arrays (npairs, m).  Returns (re, im, shift)
    where the true value is the integer times 2**shift."""
    npair, m = re.shape
    top = 2 ** (bits - 1) - 1
    tscale = float(2 ** tw_bits)
    r = _bitrev(m)
    re, im = re[:, r].astype(np.int64), im[:, r].astype(np.int64)
    shift = np.zeros(npair, np.int64)
    ln = 2
    while ln <= m:
        h = ln // 2
        j = np.arange(h)
        w = np.exp(2j * np.pi * j / ln)                 # inverse: +i
        wr = np.round(w.real * tscale).astype(np.int64)
        wi = np.round(w.imag * tscale).astype(np.int64)
        a = re.reshape(npair, m // ln, ln); b = im.reshape(npair, m // ln, ln)
        ur, ui = a[:, :, :h], b[:, :, :h]
        vr, vi = a[:, :, h:], b[:, :, h:]
        # complex multiply in int32, rounded back down by the twiddle scale
        tr = (vr * wr - vi * wi + (1 << (tw_bits - 1))) >> tw_bits
        ti = (vr * wi + vi * wr + (1 << (tw_bits - 1))) >> tw_bits
        re = np.concatenate([ur + tr, ur - tr], axis=2).reshape(npair, m)
        im = np.concatenate([ui + ti, ui - ti], axis=2).reshape(npair, m)
        # renormalise to int16 storage: one shared exponent per pair
        mx = np.maximum(np.abs(re).max(1), np.abs(im).max(1))
        sh = np.maximum(0, np.ceil(np.log2(np.maximum(mx, 1) / top))).astype(np.int64)
        if sh.any():
            k = sh[:, None]
            re = (re + (1 << k >> 1)) >> k
            im = (im + (1 << k >> 1)) >> k
            shift += sh
        ln *= 2
    return re, im, shift

def modelB(P, lo, hi, bits, group):
    m = len(P)
    top = 2 ** (bits - 1) - 1
    q = np.empty(m); Q = np.empty(m, complex)
    for a in range(0, m, group):
        b = P[a:a + group]
        s = max(np.abs(b.real).max(), np.abs(b.imag).max())
        q[a:a + group] = (s / top) if s > 0 else 1.0
    qi = np.round(P.real / q).astype(np.int64)
    qq = np.round(P.imag / q).astype(np.int64)
    re, im, sh = fixed_ifft(qi[None, :], qq[None, :], bits)
    mag = np.sqrt(re[0].astype(float) ** 2 + im[0].astype(float) ** 2) * 2.0 ** sh[0]
    yq = (mag * q[0])[lo:hi].max()          # group='all' assumed for the scale
    yt = np.abs(np.fft.ifft(P) * m)[lo:hi].max()
    return yq / yt

def report_b(P):
    print("\n  full fixed-point pipeline (int16 storage, int32 butterfly)\n")
    print("  bits      median      worst low     worst high    band")
    for bits in (16, 12):
        r = np.array([modelB(p, lo, hi, bits, len(p)) for p, lo, hi in P])
        print("  %4d   %9.6f      %9.6f      %9.6f   %6.4fx" %
              (bits, np.median(r), r.min(), r.max(), r.max() / r.min()))


# ---------------------------------------------------------------- model C
# The schedule the hardware actually wants.  vpmulhrsw is a Q15 multiply that
# stays in int16 -- measured at half the cycles of an fp32 butterfly, where
# vpmaddwd's widen-and-pack ate the gain -- so nothing ever widens and there is
# no block-floating-point max reduction.  The price is that a radix-2 stage can
# double, so every stage must shift right by 1 unconditionally.
#
# That sounds like ten bits thrown away, and it is not: the vector really does
# grow by about sqrt(2) a stage, so each shift gives back half a bit of real
# growth and costs half a bit of headroom.  Ten stages should cost ~5 bits, not
# ~10.  This measures which.

def q15_ifft(re, im, fixed_shift=True):
    npair, m = re.shape
    r = _bitrev(m)
    re, im = re[:, r].astype(np.int64), im[:, r].astype(np.int64)
    shift = 0
    ln = 2
    while ln <= m:
        h = ln // 2
        j = np.arange(h)
        w = np.exp(2j * np.pi * j / ln)
        wr = np.round(w.real * 32768).clip(-32768, 32767).astype(np.int64)
        wi = np.round(w.imag * 32768).clip(-32768, 32767).astype(np.int64)
        a = re.reshape(npair, m // ln, ln); b = im.reshape(npair, m // ln, ln)
        ur, ui = a[:, :, :h], b[:, :, :h]
        vr, vi = a[:, :, h:], b[:, :, h:]
        # vpmulhrsw: (x*y + 0x4000) >> 15, saturating, result stays int16
        def mulhrs(x, y): return np.clip((x * y + 16384) >> 15, -32768, 32767)
        tr = mulhrs(vr, wr) - mulhrs(vi, wi)
        ti = mulhrs(vr, wi) + mulhrs(vi, wr)
        re = np.concatenate([ur + tr, ur - tr], axis=2).reshape(npair, m)
        im = np.concatenate([ui + ti, ui - ti], axis=2).reshape(npair, m)
        if fixed_shift:                      # unconditional, no reduction
            re = (re + 1) >> 1; im = (im + 1) >> 1; shift += 1
        re = np.clip(re, -32768, 32767); im = np.clip(im, -32768, 32767)
        ln *= 2
    return re, im, shift

def modelC(P, lo, hi, bits=16):
    m = len(P); top = 2 ** (bits - 1) - 1
    s = max(np.abs(P.real).max(), np.abs(P.imag).max())
    q = s / top
    qi = np.round(P.real / q).astype(np.int64)[None, :]
    qq = np.round(P.imag / q).astype(np.int64)[None, :]
    re, im, sh = q15_ifft(qi, qq)
    mag = np.sqrt(re[0].astype(float) ** 2 + im[0].astype(float) ** 2) * 2.0 ** sh
    yt = np.abs(np.fft.ifft(P) * m)[lo:hi].max()
    return (mag * q)[lo:hi].max() / yt


# ---------------------------------------------------------------- model D
# End to end, exactly what the kernel would do.  The data spectrum and the
# template are each quantised to Q15 once (per block and per ingest, so free in
# the steady state) and the product is formed by the same vpmulhrsw that does
# the butterflies -- it is not a float product that is then rounded.  That
# matters: a bin where both operands are small produces zero, which is a
# different loss from rounding the true product.

def modelD(D, H, lo, hi):
    m = len(D)
    def q15(x):
        s = max(np.abs(x.real).max(), np.abs(x.imag).max())
        q = s / 32767.0
        return (np.round(x.real / q).astype(np.int64),
                np.round(x.imag / q).astype(np.int64), q)
    dr, di, qd = q15(D)
    hr, hi_, qh = q15(H)
    def mulhrs(x, y): return np.clip((x * y + 16384) >> 15, -32768, 32767)
    pr = mulhrs(dr, hr) - mulhrs(di, hi_)
    pi = mulhrs(dr, hi_) + mulhrs(di, hr)
    pr = np.clip(pr, -32768, 32767); pi = np.clip(pi, -32768, 32767)
    re, im, sh = q15_ifft(pr[None, :], pi[None, :])
    mag = np.sqrt(re[0].astype(float) ** 2 + im[0].astype(float) ** 2) * 2.0 ** sh
    # the Q15 product carries a factor 2**-15 relative to the true product
    scale = qd * qh * 32768.0
    yt = np.abs(np.fft.ifft(D * H) * m)[lo:hi].max()
    return (mag * scale)[lo:hi].max() / yt


# ---------------------------------------------------------------- model E
# The product is 4% of the work and was carrying all of the error, because a
# Q15 multiply rounds each partial product before the subtract and pins the
# output scale to the product of the two operand maxima -- which occur at
# different bins, so the result never fills int16's range and the unused
# headroom is thrown-away precision.
#
# So the product, and only the product, widens: vpmaddwd gives (dr*hr - di*hi)
# exactly in int32, and one shift per pair renormalises to full scale.  That is
# the rule the machine notes imply -- madd loses on butterflies because the
# pack-back dominates, but here it is paid once against ten stages.

def modelE(D, H, lo, hi):
    m = len(D)
    def q15(x):
        s = max(np.abs(x.real).max(), np.abs(x.imag).max())
        q = s / 32767.0
        return (np.round(x.real / q).astype(np.int64),
                np.round(x.imag / q).astype(np.int64), q)
    dr, di, qd = q15(D)
    hr, hi_, qh = q15(H)
    pr = dr * hr - di * hi_          # exact, int32
    pi = dr * hi_ + di * hr
    mx = max(np.abs(pr).max(), np.abs(pi).max())
    sh = max(0, int(np.ceil(np.log2(max(mx, 1) / 32767.0))))
    pr = (pr + (1 << sh >> 1)) >> sh
    pi = (pi + (1 << sh >> 1)) >> sh
    re, im, s2 = q15_ifft(pr[None, :], pi[None, :])
    mag = np.sqrt(re[0].astype(float) ** 2 + im[0].astype(float) ** 2) * 2.0 ** s2
    scale = qd * qh * (2.0 ** sh)
    yt = np.abs(np.fft.ifft(D * H) * m)[lo:hi].max()
    return (mag * scale)[lo:hi].max() / yt
