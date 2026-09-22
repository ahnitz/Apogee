#!/usr/bin/env python3
"""Search streaming register programs for a predictor of the coarse maximum.

A candidate is a tiny machine: S real registers, one pass over the band
product, and L instructions executed per sample.  Each instruction combines a
register with either another register or a channel of the current sample.
Nothing is assumed to be linear, or sensible -- the point is to let the search
exploit whatever the operations do.

Fitness is the BRACKET WIDTH, the ratio of the largest to the smallest
truth/prediction over real captured pairs.  That is what decides how many
pairs a gate could settle without running the transform; reconstruction
accuracy is the wrong objective.  1.0 is perfect, and anything above about
1.2 is useless because the gate sits only ~1.7x above the typical maximum.

    python tools/stream_search.py --iters 4000 --regs 4 --len 8
"""
import argparse
import glob
import numpy as np

CHANNELS = ("re", "im", "mag", "mag2", "k")
# Constant operands.  Without them the machine cannot build a phasor -- a
# rotation needs R = R*cos - R'*sin -- nor any threshold, so it can only ever
# combine data with data.  The first search converged to a leaky sum of |P|
# for exactly that reason.
CONSTS = (-1.0, -0.5, 0.25, 0.5, 0.7071067811865476, 0.9, 0.99, 1.0,
          1.5, 2.0, 3.0, 0.9987954562051724, 0.049067674327418015)
OPS = ("add", "sub", "mul", "max", "min", "absdiff", "addsq", "mulacc")


def apply_op(op, a, b):
    if op == 0: return a + b
    if op == 1: return a - b
    if op == 2: return a * b
    if op == 3: return np.maximum(a, b)
    if op == 4: return np.minimum(a, b)
    if op == 5: return np.abs(a - b)
    if op == 6: return a + b * b
    return a * 0.99 + b            # leaky accumulate


def load(nblk=8, stride=3, nfiles=6):
    """Band products and their true coarse maxima, from captured segments."""
    files = sorted(glob.glob(
        "/home/ahnitz/projects/claude/searchdev/work/fixtures/hier-*.npz"))[:nfiles]
    rng = np.random.default_rng(5)
    Ps, Ts = [], []
    for path in files:
        z = np.load(path)
        n, m = int(z["n_fft"]), int(z["band"])
        series, H = z["series"], z["templates"]
        st, ws, we = z["starts"], z["win_start"], z["win_end"]
        for bi in rng.choice(len(st), nblk, replace=False):
            blk = np.zeros(n, np.complex64); s0 = int(st[bi])
            have = min(n, max(0, len(series) - s0))
            blk[:have] = series[s0:s0 + have]
            D = np.fft.fft(blk) / n
            lo, hi = int(ws[bi]), int(we[bi]); r = n // m
            a, b = max(0, lo // r - 1), min(m, (hi + r - 1) // r)
            for t in range(0, len(H), stride):
                P = (D * H[t]).astype(np.complex128)[:m]
                Ps.append(P)
                Ts.append(np.abs(np.fft.ifft(P) * m)[a:b].max())
    P = np.array(Ps); T = np.array(Ts)
    # scale so the registers work in a sane range whatever the capture
    s = np.abs(P).mean()
    return P / s, T / s, m


def run(prog, S, ch):
    """Execute one program over the stream.  ch[c] is [m, npairs]."""
    npair = ch[0].shape[1]
    R = np.zeros((S, npair))
    m = ch[0].shape[0]
    for k in range(m):
        for (dst, op, kind, src) in prog:
            b = (R[src] if kind == 0 else
                 (ch[src][k] if kind == 1 else CONSTS[src]))
            R[dst] = apply_op(op, R[dst], b)
        np.clip(R, -1e12, 1e12, out=R)
    return R


def fitness(pred, T):
    if not np.all(np.isfinite(pred)):
        return 1e9
    p = np.abs(pred)
    if (p <= 0).any():
        return 1e9
    r = T / p
    lo, hi = np.percentile(r, 0.5), np.percentile(r, 99.5)
    if lo <= 0:
        return 1e9
    return hi / lo


def nsrc(kind, S):
    return S if kind == 0 else (len(CHANNELS) if kind == 1 else len(CONSTS))


def readout(R, T, S):
    """Best single register, or ratio of two -- so it can normalise itself."""
    best = 1e9
    for i in range(S):
        f = fitness(R[i], T)
        if f < best: best = f
        for j in range(S):
            if i == j: continue
            with np.errstate(all="ignore"):
                f = fitness(R[i] / np.where(R[j] == 0, np.nan, R[j]), T)
            if f < best: best = f
    return best


def rand_instr(rng, S):
    kind = int(rng.integers(3))     # register, channel, or constant
    return (int(rng.integers(S)), int(rng.integers(len(OPS))), kind,
            int(rng.integers(nsrc(kind, S))))


def rand_prog(rng, S, L):
    return [rand_instr(rng, S) for _ in range(L)]


def mutate(prog, rng, S):
    p = [list(i) for i in prog]
    i = int(rng.integers(len(p)))
    f = int(rng.integers(4))
    if f == 0: p[i][0] = int(rng.integers(S))
    elif f == 1: p[i][1] = int(rng.integers(len(OPS)))
    elif f == 2:
        p[i][2] = int(rng.integers(2))
        p[i][3] = int(rng.integers(S if p[i][2] == 0 else len(CHANNELS)))
    else: p[i][3] = int(rng.integers(S if p[i][2] == 0 else len(CHANNELS)))
    return [tuple(i) for i in p]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=2000)
    ap.add_argument("--regs", type=int, default=4)
    ap.add_argument("--len", type=int, default=8)
    ap.add_argument("--restarts", type=int, default=20)
    a = ap.parse_args()

    P, T, m = load()
    ch = [np.ascontiguousarray(x.T) for x in
          (P.real, P.imag, np.abs(P), np.abs(P) ** 2,
           np.tile(np.arange(m) / m, (len(P), 1)))]
    print("%d pairs, m=%d, %d registers, %d instructions" % (len(T), m, a.regs, a.len))
    print("flops per pair: ~%d against the transform's %d\n"
          % (a.len * m * 2, 5 * m * int(np.log2(m))))
    rng = np.random.default_rng(0)
    best, bprog = 1e9, None
    per = max(1, a.iters // a.restarts)
    for r in range(a.restarts):
        prog = rand_prog(rng, a.regs, a.len)
        cur = readout(run(prog, a.regs, ch), T, a.regs)
        for _ in range(per):
            cand = mutate(prog, rng, a.regs)
            R = run(cand, a.regs, ch)
            f = readout(R, T, a.regs)
            if f < cur:
                cur, prog = f, cand
        if cur < best:
            best, bprog = cur, prog
            print("  restart %2d: bracket width %.3f" % (r, best))
    print("\nbest bracket width: %.3f" % best)
    print("(the interpolated statistic, which needs the transform already done,"
          " is 1.14;\n anything above ~1.2 settles no pairs at our gate)")
    if bprog:
        print("\nprogram:")
        for (d, o, kind, s) in bprog:
            src = ("R%d" % s if kind == 0 else
                   (CHANNELS[s] if kind == 1 else "%.6g" % CONSTS[s]))
            print("   R%d = %-8s(R%d, %s)" % (d, OPS[o], d, src))


if __name__ == "__main__":
    main()
