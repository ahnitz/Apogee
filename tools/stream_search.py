#!/usr/bin/env python3
"""Search streaming register programs for a predictor of the coarse maximum.

A candidate is a tiny machine: S registers, one pass over the band product,
L three-address instructions per sample.  Nothing is assumed to be linear or
numerically sensible -- bit-level reinterpretation is in the op set precisely
because a float's bit pattern read as an integer is an approximate log2, so
integer arithmetic on it approximates multiplication of the values.

Fitness is BRACKET WIDTH: the ratio of the largest to the smallest
truth/prediction over real captured pairs.  That is what decides how many
pairs a margin settles without running the transform.  1.0 is perfect; above
about 1.2 settles nothing, because the coarse threshold sits only ~1.7x above a typical
maximum.

An earlier version of this was far too restrictive and its negative result
meant little: instructions were two-address, so a register could only
accumulate into itself, which makes a rotation -- and therefore anything
Fourier-like -- unreachable.  One restart is now seeded with Goertzel so the
search starts inside that basin rather than having to find it.

    python tools/stream_search.py --iters 20000 --regs 6 --len 10
"""
import argparse
import glob
import multiprocessing as mp
import os
import numpy as np

CH = ("re", "im", "mag", "mag2", "k", "one")
OPS = ("add", "sub", "mul", "max", "min", "absdiff", "div", "sqrtabs",
       "rsqrt", "gt", "bitadd", "bitsub", "bitshr", "bitxor", "fma1")


def _bits(x):
    return np.asarray(x, np.float32).view(np.int32).astype(np.float64)


def _unbits(x):
    return (np.clip(np.asarray(x), -2**31, 2**31 - 1)
            .astype(np.int32).view(np.float32).astype(np.float64))


def apply_op(op, a, b):
    with np.errstate(all="ignore"):
        if op == 0:  return a + b
        if op == 1:  return a - b
        if op == 2:  return a * b
        if op == 3:  return np.maximum(a, b)
        if op == 4:  return np.minimum(a, b)
        if op == 5:  return np.abs(a - b)
        if op == 6:  return a / np.where(np.abs(b) < 1e-30, 1e-30, b)
        if op == 7:  return np.sqrt(np.abs(a))
        if op == 8:  return 1.0 / np.sqrt(np.abs(a) + 1e-30)
        if op == 9:  return (a > b).astype(np.float64)
        # bit-level: a float's bits read as an int are an approximate log2
        if op == 10: return _unbits(_bits(a) + _bits(b))
        if op == 11: return _unbits(_bits(a) - _bits(b))
        if op == 12: return _unbits(_bits(a) * 0.5)
        if op == 13: return _unbits(np.bitwise_xor(
            _bits(a).astype(np.int64), _bits(b).astype(np.int64)).astype(np.float64))
        return a + a * b


def load(nblk=8, stride=3, nfiles=6):
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
                Ps.append(P); Ts.append(np.abs(np.fft.ifft(P) * m)[a:b].max())
    P = np.array(Ps); T = np.array(Ts)
    s = np.abs(P).mean()
    return P / s, T / s, m


def run(prog, S, ch, consts, cv=None):
    npair = ch[0].shape[1]; m = ch[0].shape[0]
    R = np.zeros((S, npair))
    if cv is None:
        cv = [np.full(npair, c) for c in consts]
    def operand(kind, idx, k):
        if kind == 0: return R[idx]
        if kind == 1: return ch[idx][k]
        return cv[idx]
    for k in range(m):
        for (dst, op, ka, ia, kb, ib) in prog:
            R[dst] = apply_op(op, operand(ka, ia, k), operand(kb, ib, k))
        np.clip(R, -1e15, 1e15, out=R)
        np.nan_to_num(R, copy=False, nan=0.0, posinf=1e15, neginf=-1e15)
    return R


def fitness(p, T):
    if not np.all(np.isfinite(p)): return 1e9
    p = np.abs(p)
    if (p <= 0).any(): return 1e9
    r = T / p
    lo, hi = np.percentile(r, 0.5), np.percentile(r, 99.5)
    return 1e9 if lo <= 0 else hi / lo


def readout(R, T, S):
    best = 1e9
    for i in range(S):
        f = fitness(R[i], T)
        if f < best: best = f
    return best


def nsrc(kind, S, nc):
    return (S, len(CH), nc)[kind]


def rand_instr(rng, S, nc):
    ka, kb = int(rng.integers(3)), int(rng.integers(3))
    return (int(rng.integers(S)), int(rng.integers(len(OPS))),
            ka, int(rng.integers(nsrc(ka, S, nc))),
            kb, int(rng.integers(nsrc(kb, S, nc))))


def mutate(prog, rng, S, nc):
    p = [list(i) for i in prog]
    i = int(rng.integers(len(p)))
    f = int(rng.integers(4))
    if f == 0: p[i][0] = int(rng.integers(S))
    elif f == 1: p[i][1] = int(rng.integers(len(OPS)))
    elif f == 2:
        p[i][2] = int(rng.integers(3)); p[i][3] = int(rng.integers(nsrc(p[i][2], S, nc)))
    else:
        p[i][4] = int(rng.integers(3)); p[i][5] = int(rng.integers(nsrc(p[i][4], S, nc)))
    return [tuple(x) for x in p]


def goertzel_seed(S, consts):
    """R0,R1 = a rotating phasor; R2,R3 accumulate the projection onto it.
    This is the correlation at one lag, which the search should be able to
    reach and improve on rather than having to invent."""
    c = consts.index(0.9987954562051724); s = consts.index(0.049067674327418015)
    one = CH.index("one"); re = CH.index("re"); im = CH.index("im")
    return [(4, 2, 0, 0, 2, c),      # R4 = R0*cos
            (5, 2, 0, 1, 2, s),      # R5 = R1*sin
            (0, 1, 0, 4, 0, 5),      # R0 = R4 - R5
            (1, 14, 0, 1, 2, c),     # R1 = R1 + R1*cos  (rough)
            (2, 0, 0, 2, 1, re),     # R2 += re
            (3, 0, 0, 3, 1, im)][:S + 2]


_W = {}


def _init(P, T, m, consts, S, L, iters):
    """Per-worker setup: build the channel views once, not per restart."""
    ch = [np.ascontiguousarray(x.T) for x in
          (P.real, P.imag, np.abs(P), np.abs(P) ** 2,
           np.tile(np.arange(m) / m, (len(P), 1)), np.ones((len(P), m)))]
    _W.update(ch=ch, T=T, consts=consts, S=S, L=L, iters=iters,
              cv=[np.full(len(T), c) for c in consts])


def _restart(seed):
    ch, T, consts = _W["ch"], _W["T"], _W["consts"]
    S, L, iters, cv = _W["S"], _W["L"], _W["iters"], _W["cv"]
    rng = np.random.default_rng(seed)
    if seed == 0:
        prog = goertzel_seed(S, consts)
        while len(prog) < L: prog.append(rand_instr(rng, S, len(consts)))
        prog = prog[:L]
    else:
        prog = [rand_instr(rng, S, len(consts)) for _ in range(L)]
    cur = readout(run(prog, S, ch, consts, cv), T, S)
    stall = 0
    for _ in range(iters):
        cand = mutate(prog, rng, S, len(consts))
        f = readout(run(cand, S, ch, consts, cv), T, S)
        if f < cur - 1e-9:
            cur, prog, stall = f, cand, 0
        else:
            stall += 1
            if stall > iters // 3:      # exhausted: jump somewhere new
                prog = [rand_instr(rng, S, len(consts)) for _ in range(L)]
                cur = readout(run(prog, S, ch, consts, cv), T, S)
                stall = 0
    return cur, prog


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=8000)
    ap.add_argument("--regs", type=int, default=6)
    ap.add_argument("--len", type=int, default=10)
    ap.add_argument("--restarts", type=int, default=30)
    ap.add_argument("--workers", type=int, default=0)
    a = ap.parse_args()
    consts = [-1.0, -0.5, 0.25, 0.5, 0.7071067811865476, 0.9, 0.99, 1.0, 1.5,
              2.0, 3.0, 0.9987954562051724, 0.049067674327418015]
    P, T, m = load()
    print("%d pairs, m=%d, %d registers, %d three-address instructions" %
          (len(T), m, a.regs, a.len))
    print("ops: %s" % ", ".join(OPS))
    print("flops/pair ~%d against the transform's %d\n" % (a.len * m * 2, 5 * m * 10))
    nw = a.workers or min(os.cpu_count() or 1, a.restarts)
    print("searching on %d cores, %d restarts x %d mutations\n"
          % (nw, a.restarts, max(1, a.iters // a.restarts)))
    per = max(1, a.iters // a.restarts)
    with mp.Pool(nw, initializer=_init,
                 initargs=(P, T, m, consts, a.regs, a.len, per)) as pool:
        best, bprog = 1e9, None
        for i, (f, prog) in enumerate(
                pool.imap_unordered(_restart, range(a.restarts))):
            if f < best:
                best, bprog = f, prog
                print("  %4d/%d   bracket width %.4f" % (i + 1, a.restarts, best))
    print("\nbest bracket width: %.3f   (need <1.2 to settle anything)" % best)
    if bprog:
        print("\nprogram:")
        for (d, o, ka, ia, kb, ib) in bprog:
            def nm(k, i):
                if k == 0: return "R%d" % i
                if k == 1: return CH[i]
                return "%.6g" % consts[i]
            print("   R%d = %-8s(%s, %s)" % (d, OPS[o], nm(ka, ia), nm(kb, ib)))


if __name__ == "__main__":
    main()
