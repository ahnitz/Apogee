"""Offline design sweep for the hierarchical matched filter.

Emits the compiled-in table (R, U, K, t_c) that src/hmf.c uses.  Nothing here
runs at run time -- matchedfilter does no autotuning; this produces measured constants.

Model
-----
With the band split, rho_c = sqrt(f)*rho_full + sqrt(1-f)*xi, xi independent.
So conditional on the full-filter value rho, the coarse value is Gaussian about
sqrt(f)*rho, and the false-dismissal probability is a Rice CDF -- analytic.
That matters: at FD=1e-4 a Monte Carlo quantile has a handful of events in the
tail and is far too noisy to design against.  Monte Carlo is used only to check
the model, in validate().

The deterministic part -- how much of the coarse peak the sampling grid plus
interpolator actually recovers -- is measured, not modelled, since it depends on
the template shape.  That is g(N,R,U,K) below.
"""
import numpy as np
from scipy.stats import rice, norm
from scipy.integrate import quad


def _rice_cdf(x, nu, sd):
    """Rice CDF with mean parameter nu and scale sd, vectorised.

    scipy's rice.cdf goes through ncx2, whose series converges slowly once the
    noncentrality is large -- and here b = nu/sd runs up to ~60, which made the
    design sweep hundreds of times slower than its own arithmetic warrants.
    Above b ~ 15 the Rice distribution is Gaussian to far better than the
    precision this design needs, so switch there.
    """
    x = np.asarray(x, float); nu = np.asarray(nu, float)
    b = nu / sd
    big = b > 15.0
    out = np.empty(np.broadcast(x, nu).shape, float)
    if np.any(~big):
        bb = np.broadcast_arrays(x, b)
        out = np.where(~big, rice.cdf(bb[0], b=np.where(big, 1.0, bb[1]), scale=sd), 0.0)
    if np.any(big):
        out = np.where(big, norm.cdf((x - nu) / sd), out)
    return out


def false_dismissal(t_c, f, g, T, tdet=None):
    """P(coarse peak < t_c | full filter detects), for sources at SNR T.

    Conditional on the full-filter value rho, the coarse value is
    Rice(g*sqrt(f)*|rho|, sqrt(1-f)).  |rho| itself is Rice(T, 1), truncated to
    the detection threshold.  Marginalising over it is a 1-D integral.

    Conditioning matters twice over.  Dropping it entirely makes the estimate
    ~10x optimistic (it counts events the full filter never detected).  Pinning
    rho to the threshold instead of integrating makes it ~10x conservative,
    which is safe but sets t_c too low and inflates the trigger rate.
    """
    if tdet is None: tdet = T
    sd = np.sqrt(max(1e-9, 1.0 - f * g ** 2))
    norm = rice.sf(tdet, b=T, scale=1.0)
    if norm <= 0: return 0.0
    def integrand(r):
        return rice.cdf(t_c, b=g * np.sqrt(f) * r / sd, scale=sd) * rice.pdf(r, b=T, scale=1.0)
    hi = tdet + 12.0
    val, _ = quad(integrand, tdet, hi, limit=200)
    return val / norm


_TC_CACHE = {}


def solve_tc(alpha, f, g, T, tdet=None):
    """Largest t_c whose false-dismissal probability is at most alpha.

    Memoised on the effective band fraction: the sweep evaluates many (R,U,K)
    candidates that share an f*g^2, and each repeat is a full curve evaluation.

    Inverted by evaluating the whole FD curve at once rather than bisecting.
    Bisection re-integrates from scratch at every step -- 60 quadratures per
    call, ~45k per size -- which dominated the entire sweep.  The curve is
    monotone, so one vectorised pass plus an interpolation is exact enough and
    roughly a hundred times faster.
    """
    if tdet is None: tdet = T
    key = (round(alpha, 12), round(f * g * g, 6), round(T, 4), round(tdet, 4))
    hit = _TC_CACHE.get(key)
    if hit is not None: return hit
    sd = np.sqrt(max(1e-9, 1.0 - f * g ** 2))
    norm = rice.sf(tdet, b=T, scale=1.0)
    if norm <= 0: return 0.0
    r = np.linspace(tdet, tdet + 12.0, 257)
    pdf = rice.pdf(r, b=T, scale=1.0)
    tg = np.linspace(0.0, g * np.sqrt(f) * (T + 8.0), 400)
    # FD(t) = int cdf(t | r) pdf(r) dr, evaluated for every t at once
    cdf = _rice_cdf(tg[:, None], g * np.sqrt(f) * r[None, :], sd)
    fdv = np.trapezoid(cdf * pdf[None, :], r, axis=1) / norm
    idx = np.searchsorted(fdv, alpha)
    if idx <= 0: out = float(tg[0])
    elif idx >= tg.size: out = float(tg[-1])
    else:
        f0, f1 = fdv[idx - 1], fdv[idx]
        if f1 <= f0: out = float(tg[idx - 1])
        else:
            w = (alpha - f0) / (f1 - f0)
            out = float(tg[idx - 1] + w * (tg[idx] - tg[idx - 1]))
    _TC_CACHE[key] = out
    return out

#: POWER fraction of the design template below the reference band edge.
#:
#: Two things are easy to conflate here.  This is power, not SNR: 0.85 of the
#: power is sqrt(0.85) = 0.92 of the SNR, so quoting "85%" of one when the other
#: is meant changes the template's concentration substantially.
#:
#: The band edge is fixed in Hz, not in bins.  At a 2048 Hz sample rate, 256 Hz
#: lands at bin 256*n/2048 = n/8 for any n, so the fractional band n/8 is the
#: right reference and stays right as n grows -- more samples means more time
#: analysed, not more bandwidth.  A fixed power-law exponent would NOT be
#: scale-invariant: f^-0.9 puts 99% of its power below n/8 by 2^20.
#:
#: This only selects the BAND.  Each template's own f and recovery factors are
#: measured at ingest, so a template that does not match this assumption gets a
#: correct margin regardless -- the cost of a mismatch is efficiency, not
#: detections.
POWER_FRAC = 0.85
SNR_FRAC = POWER_FRAC ** 0.5


def make_template(n, m_ref, want_f):
    """Analytic template with power fraction want_f in bins [0, m_ref)."""
    fr = np.arange(1, n // 2).astype(float)
    def frac(s, m):
        p = fr ** (2 * s)
        return p[: m - 1].sum() / p.sum()
    lo, hi = -8.0, 4.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if frac(mid, m_ref) < want_f: hi = mid
        else: lo = mid
    H = np.zeros(n, complex)
    H[1 : n // 2] = fr ** (0.5 * (lo + hi))
    H /= np.sqrt((np.abs(H) ** 2).sum())
    return H

def kernel(K, d, U):
    """Normalised interpolation taps.  U=1 is critically sampled and needs the
    analytic (Dirichlet) kernel unwindowed; U>1 has headroom, where centring the
    band and applying Kaiser measures best."""
    k = np.arange(-K // 2 + 1, K // 2 + 1)
    x = d - k
    s = np.sinc(x)
    if U == 1:
        return k, (s / s.sum()) * np.exp(1j * np.pi * x)
    t = (np.arange(K) - (K - 1) / 2) / max((K - 1) / 2, 1e-9)
    w = s * np.i0(5.0 * np.sqrt(np.maximum(0, 1 - t ** 2))) / np.i0(5.0)
    return k, (w / w.sum()).astype(complex)

def recovery(H, n, m, U, K, nsub=8):
    """Worst-case fraction of the ideal coarse peak recovered, as (raw, interp).

    Both are needed and they are not interchangeable.  The margin threshold is
    calibrated against the INTERPOLATED figure.  The cheap pre-scan that decides
    which samples are worth interpolating must use the RAW figure -- using the
    interpolated one there discards exactly the samples interpolation exists to
    rescue, silently adding false dismissals on top of the calibrated rate.
    """
    G = m * U
    Hl = H.copy(); Hl[m:] = 0
    Hn = Hl / np.sqrt((np.abs(Hl) ** 2).sum())
    cen = np.exp(-1j * np.pi * np.arange(G) / U) if U > 1 else np.ones(G)
    offs = np.arange(1, nsub) / float(nsub)
    bank = [kernel(K, d, U) for d in offs]
    worst = 9.0; worst_raw = 9.0
    R = n // m
    # Sample the sub-grid offsets evenly rather than exhaustively.  At large N
    # with a small band there can be hundreds of them, and the worst case is the
    # half-step, which even sampling always brackets.
    nstep = max(1, R // U)
    stride = max(1, nstep // 16)
    for s in range(0, nstep, stride):        # sub-grid offsets within one step
        lag = s
        D = H * np.exp(-2j * np.pi * np.arange(n) * lag / n)
        P = (D * np.conj(Hn))[:m]
        Q = np.concatenate([P, np.zeros(m * (U - 1), complex)]) if U > 1 else P
        rc = np.fft.ifft(Q) * (m * U)
        truth = np.abs(np.fft.ifft(np.concatenate(
            [P, np.zeros(m * (8 * U - 1), complex)])) * (m * 8 * U)).max()
        rb = rc * cen
        j0 = int(np.argmax(np.abs(rc)))
        best = abs(rc[j0])
        worst_raw = min(worst_raw, best / truth)
        for b0 in (j0 - 1, j0):
            for d, (k, w) in zip(offs, bank):
                v = np.dot(w, rb[(b0 + k) % G])
                if U > 1: v *= np.exp(1j * np.pi * (b0 + d) / U)
                best = max(best, abs(v))
        worst = min(worst, best / truth)
    return worst_raw, worst

#: Measured cost of a matched-filter pair transform, in ps per n*log2(n), by
#: transform size.  Small transforms do NOT reach their flop bound -- 256 points
#: costs 90 ps against 69 at 4096 -- so pricing the coarse pass in raw flops
#: under-charges small bands and makes the design buy too little band.
_RATE = {256: 90.2, 512: 83.3, 1024: 76.5, 2048: 75.7, 4096: 69.2,
         8192: 67.8, 16384: 68.5}


def _cost_units(m):
    """Cost of an m-point pair transform: flops weighted by measured efficiency."""
    r = _RATE.get(m)
    if r is None:
        keys = sorted(_RATE)
        r = _RATE[keys[0]] if m < keys[0] else _RATE[keys[-1]]
    return 5.0 * m * np.log2(m) * r


def design(n, want_f=POWER_FRAC, taps=(4, 8, 12),
           Rs=(2, 4, 8, 16, 32, 64, 128, 256, 512, 1024),
           Ts=(5.0, 5.5, 6.0), FDs=(1e-2, 1e-3, 1e-4), window=1.0):
    """Best (R,U,K) per (T,FD), with the cost model in units of the full inverse."""
    H = make_template(n, n // 8, want_f)
    pw = np.abs(H) ** 2
    full = _cost_units(n)
    cand = []
    for R in Rs:
        m = n // R
        # The coarse pass is an m-point transform, so m must be a size matchedfilter
        # supports.  256 is the floor: below it one half of the balanced split
        # falls under the AVX-512 lane count.  This is a real constraint, not a
        # tuning choice -- the unconstrained optimum often wants 64 or 128, so
        # supporting smaller transforms would unlock more speedup.
        if m < 256: continue
        f = float(pw[:m].sum())
        for U in (1, 2):
            G = m * U
            if G > n: continue
            for K in taps:
                graw, g = recovery(H, n, m, U, K)
                # Raw recovery of the EVEN half alone, i.e. the U=1 series at the
                # same band.  At run time the even transform is done first; if
                # its maximum is below graw1*margin the true peak cannot reach the
                # margin, so the odd transform can be skipped entirely.  In noise
                # that is almost always, which halves the coarse cost.
                graw1, _ = recovery(H, n, m, 1, K)
                cand.append(dict(R=R, U=U, K=K, m=m, G=G, f=f,
                                 g=g, graw=graw, graw1=graw1))
    out = {}
    for T in Ts:
        for a in FDs:
            best = None
            for c in cand:
                t_c = solve_tc(a, c['f'], c['g'], T)
                if not np.isfinite(t_c) or t_c <= 0: continue
                trig = 1.0 - np.exp(-c['G'] * window * np.exp(-t_c ** 2 / 2))
                ncand = max(1.0, c['G'] * window * np.exp(-t_c ** 2 / 2))
                # The odd half of a U=2 grid only runs when the even half clears
                # graw1*t_c, which on noise is a minority of pairs.  Charging
                # both halves unconditionally made U=2 look twice as expensive
                # as it is and pushed the design toward bands that are too
                # narrow -- which costs f, and f is what sets the trigger rate.
                p_odd = 1.0
                if c['U'] > 1:
                    eg = t_c * c['graw1']
                    p_odd = 1.0 - np.exp(-c['m'] * window * np.exp(-eg ** 2 / 2))
                xf = _cost_units(c['m']) * (1.0 + p_odd * (c['U'] - 1))
                cost = (xf + (2.0 * c['G'] + c['K'] * 16 * ncand) * 60.0) / full + trig
                row = dict(c, t_c=t_c, trig=trig, cost=cost, speed=1.0 / cost)
                if best is None or row['speed'] > best['speed']: best = row
            out[(T, a)] = best
    return out

def validate(n, R, U, K, T, ntrial=40000, seed=5):
    """Check the Rice model against Monte Carlo at one operating point."""
    rng = np.random.default_rng(seed)
    H = make_template(n, n // 8, POWER_FRAC)
    m = n // R; G = m * U
    Hl = H.copy(); Hl[m:] = 0
    f = float((np.abs(Hl) ** 2).sum()); Hn = Hl / np.sqrt(f)
    _graw, g = recovery(H, n, m, U, K)
    cen = np.exp(-1j * np.pi * np.arange(G) / U) if U > 1 else np.ones(G)
    offs = np.arange(1, 8) / 8.0
    bank = [kernel(K, d, U) for d in offs]
    rc, rf = [], []
    done = 0
    while done < ntrial:
        b = min(2000, ntrial - done); done += b
        lag = rng.integers(0, n, size=b)
        N = rng.standard_normal((b, n)) + 1j * rng.standard_normal((b, n))
        D = N + T * H[None, :] * np.exp(-2j * np.pi * np.outer(lag, np.arange(n)) / n)
        # false dismissal is defined relative to what the FULL filter detects,
        # so the full-filter value at the injected lag has to be carried too
        rho = np.fft.ifft(D * np.conj(H)[None, :], axis=1) * n
        rf.append(np.abs(rho[np.arange(b), lag]))
        P = (D * np.conj(Hn)[None, :])[:, :m]
        if U > 1: P = np.concatenate([P, np.zeros((b, m * (U - 1)), complex)], axis=1)
        q = np.fft.ifft(P, axis=1) * (m * U) * cen[None, :]
        gi = (lag * G) // n
        ar = np.arange(b)
        best = np.maximum(np.abs(q[ar, gi % G]), np.abs(q[ar, (gi + 1) % G]))
        for d, (k, w) in zip(offs, bank):
            idx = (gi[:, None] + k[None, :]) % G
            v = (q[ar[:, None], idx] * w[None, :]).sum(1)
            if U > 1: v = v * np.exp(1j * np.pi * (gi + d) / U)
            best = np.maximum(best, np.abs(v))
        rc.append(best)
    rc = np.concatenate(rc); rf = np.concatenate(rf)
    keep = rf >= T                      # only events the full filter would report
    rc = rc[keep]
    print(f"  kept {keep.sum()} of {keep.size} injections (full filter >= T)")
    print(f"  N={n} R={R} U={U} K={K} T={T}:  f={f:.3f} g={g:.3f}")
    print(f"  {'t_c':>6} {'model FD':>10} {'measured FD':>12}")
    for a in (1e-1, 3e-2, 1e-2, 3e-3):
        t_c = solve_tc(a, f, g, T)
        print(f"  {t_c:>6.3f} {a:>10.2e} {np.mean(rc < t_c):>12.2e}")


THRESHOLD_C = """
static float hmf_threshold(float f_eff, float snr, float fd)
{
  int ai = 0; float bd = 1e30f;
  for (int i = 0; i < HMF_NFD; i++) {
    float d = fd > hmf_fd_grid[i] ? fd / hmf_fd_grid[i] : hmf_fd_grid[i] / fd;
    if (d < bd) { bd = d; ai = i; }
  }
  /* Clamp rather than extrapolate.  Outside the grid the model is untested, and
     a clamped threshold errs toward triggering more often, which costs time but
     cannot cost a detection. */
  if (f_eff <= hmf_f_grid[0]) f_eff = hmf_f_grid[0];
  if (f_eff >= hmf_f_grid[HMF_NF-1]) f_eff = hmf_f_grid[HMF_NF-1];
  if (snr <= hmf_snr_grid[0]) snr = hmf_snr_grid[0];
  if (snr >= hmf_snr_grid[HMF_NSNR-1]) snr = hmf_snr_grid[HMF_NSNR-1];
  int fi = 0; while (fi < HMF_NF-2 && hmf_f_grid[fi+1] < f_eff) fi++;
  int si = 0; while (si < HMF_NSNR-2 && hmf_snr_grid[si+1] < snr) si++;
  float tf = (f_eff - hmf_f_grid[fi]) / (hmf_f_grid[fi+1] - hmf_f_grid[fi]);
  float ts = (snr - hmf_snr_grid[si]) / (hmf_snr_grid[si+1] - hmf_snr_grid[si]);
  float a = hmf_tc[ai][si][fi]   + tf * (hmf_tc[ai][si][fi+1]   - hmf_tc[ai][si][fi]);
  float b = hmf_tc[ai][si+1][fi] + tf * (hmf_tc[ai][si+1][fi+1] - hmf_tc[ai][si+1][fi]);
  return a + ts * (b - a);
}
#endif
"""

TABLE_F   = np.round(np.arange(0.30, 1.0001, 0.025), 4)
TABLE_SNR = (4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 8.0)
TABLE_FD  = (1e-2, 1e-3, 1e-4)
TABLE_N   = (1024, 2048, 4096, 8192, 16384, 32768, 65536,
             131072, 262144, 524288, 1048576)


def emit_table(path):
    """Generate the archived model table for historical experiments only."""
    # No sweep over N. This used to run design() for all eleven transform
    # lengths -- 5m31s of CI on every push -- to fill a `chosen` dict that
    # fed the compiled picks table. That table was removed in favour of the
    # measured tuning tables, and nothing has read `chosen` since: hmf_tc
    # below comes from solve_tc alone and has no N axis at all. The emitted
    # header is byte-identical without it.
    L = []; w = L.append
    w("/* Generated by tools/hmf_design.py -- do not edit by hand.")
    w(" *")
    w(" * The coarse threshold t_c: the value the first pass compares against,")
    w(" * for a given false-dismissal target.  This is the CONTINUOUS half of")
    w(" * the tuning, and it is the only thing in this file.")
    w(" *")
    w(" * Which band, oversampling and taps to use is NOT here.  That is the")
    w(" * discrete half, and it comes from the measured tuning tables shipped")
    w(" * with the package (docs/hierarchical.md).  The compiled picks that")
    w(" * used to live here were removed as a second, uncheckable answer to")
    w(" * the same question.")
    w(" *")
    w(" * t_c is tabulated against the EFFECTIVE band fraction f*g^2 rather than")
    w(" * f, so a template whose power sits differently from the design template")
    w(" * still gets a correct threshold.  Bilinear in (f_eff, snr); nearest in")
    w(" * fd, which is a discrete choice.")
    w(" */")
    w("#ifndef AP_HMF_TABLE_H")
    w("#define AP_HMF_TABLE_H")
    w("#include <stddef.h>")
    w("")
    w(f"#define HMF_NF   {len(TABLE_F)}")
    w(f"#define HMF_NSNR {len(TABLE_SNR)}")
    w(f"#define HMF_NFD  {len(TABLE_FD)}")
    w("")
    w("static const float hmf_f_grid[HMF_NF] = {")
    w("  " + ", ".join(f"{v:.4f}f" for v in TABLE_F))
    w("};")
    w("static const float hmf_snr_grid[HMF_NSNR] = {")
    w("  " + ", ".join(f"{v:.2f}f" for v in TABLE_SNR))
    w("};")
    w("static const float hmf_fd_grid[HMF_NFD] = {")
    w("  " + ", ".join(f"{v:.1e}f" for v in TABLE_FD))
    w("};")
    w("")
    w("/* t_c[fd][snr][f_eff] */")
    w("static const float hmf_tc[HMF_NFD][HMF_NSNR][HMF_NF] = {")
    for a in TABLE_FD:
        w("  { /* fd = %.0e */" % a)
        for T in TABLE_SNR:
            vals = [solve_tc(a, float(fe), 1.0, T) for fe in TABLE_F]
            w("    { " + ", ".join(f"{v:.4f}f" for v in vals) + " },")
        w("  },")
    w("};")
    w("")
    # No picks table. Which band, oversample and taps to use is decided by
    # the measured tuning tables that ship with the package; a compiled model
    # answering the same question was a second, uncheckable source of truth
    # and was removed. What stays is the coarse threshold: t_c for a given effective band
    # fraction, which is a different object.
    w(THRESHOLD_C)
    open(path, "w").write("\n".join(L) + "\n")
    print(f"  wrote {path}", flush=True)

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "emit":
        emit_table("tools/regen/legacy_hmf_table.h")
    elif len(sys.argv) > 1 and sys.argv[1] == "validate":
        validate(4096, 16, 2, 8, 5.5)
        validate(2048, 8, 2, 8, 6.0)
    else:
        for n in (2048, 4096, 8192, 16384, 65536):
            d = design(n)
            print(f"\n===== N = {n} =====")
            print(f"  {'FD':>7} {'SNR':>4} | {'R':>3} {'U':>2} {'K':>3} {'band':>6} "
                  f"{'f':>6} {'g':>6} {'t_c':>5} {'trig':>7} {'speedup':>8}")
            for a in (1e-2, 1e-3, 1e-4):
                for T in (5.0, 5.5, 6.0):
                    b = d[(T, a)]
                    print(f"  {a:>7.2%} {T:>4.1f} | {b['R']:>3} {b['U']:>2} {b['K']:>3} "
                          f"{b['m']:>6} {b['f']:>6.3f} {b['g']:>6.3f} {b['t_c']:>5.2f} "
                          f"{b['trig']:>6.2%} {b['speed']:>7.2f}x", flush=True)
