"""Price INT8/bf16 as a COARSE PREFILTER. The fine stage is unchanged.

A prefilter is not required to be accurate -- it is required not to throw
away signal. So the question is never "how wrong is the coarse max"; it is:
hold the false dismissal FIXED at what float achieves, and see what the
approximate transform then costs in escalation rate. That is the only axis
where a cheaper coarse stage can lose, and it is what the fine stage pays.

Counting threshold crossings at one fixed SNR measures the cliff, not the
format: at SNR 6 against a 4.343 gate a sizeable share of trials sit within
noise of the threshold, and any perturbation -- including bf16, which is
near-lossless -- flips a few. Hence the quantile-matched comparison below.
"""
import numpy as np, sys
sys.path.insert(0, "tools/int8")
from quant_study import (N, BAND, reference_power, whitened_product,
                         rho_float, rho_monarch_int8, rho_bf16, rho_fp16)

THR = 4.343
NOISE, INJ = 400, 400
rng = np.random.default_rng(7)
power = reference_power(N, rng)

probe = np.concatenate([whitened_product(N, BAND, power, rng) for _ in range(8)])
sig = float(np.std(np.concatenate([probe.real, probe.imag])))
SW = 127.0

print("coarse band %d of %d, Monarch 16x32, gate %.3f\n" % (BAND, N, THR))
for KSIG in (4.0, 6.0, 8.0):
    SP = 127.0 / (KSIG * sig)
    _, pk = rho_monarch_int8(whitened_product(N, BAND, power, rng), SP, SW, 1.0)
    SRQ = 127.0 / (pk / 6.0)

    def series(inject, m):
        F, I, B, H = [], [], [], []
        for _ in range(m):
            P = whitened_product(N, BAND, power, rng, inject=inject)
            F.append(rho_float(P))
            I.append(rho_monarch_int8(P, SP, SW, SRQ)[0])
            B.append(rho_bf16(P))
            H.append(rho_fp16(P))
        return F, I, B, H

    def comp_sd(a):
        v = np.concatenate(a)
        return float(np.std(np.concatenate([v.real, v.imag])))

    def maxes(inject, m):
        F, I, B, H = series(inject, m)
        return (np.array([np.abs(x).max() for x in F]),
                np.array([np.abs(x).max() for x in I]),
                np.array([np.abs(x).max() for x in B]),
                np.array([np.abs(x).max() for x in H]))

    # The gate is in units of the output's COMPONENT sigma -- that is what
    # the profile model calibrates. Normalising by the mean noise MAXIMUM
    # instead puts everything near 1.0, so every trial reads as dismissed
    # and the escalation rate reads as zero.
    _nf, _ni, _nb, _nh = series(0.0, NOISE)
    kf, ki, kb, kh = comp_sd(_nf), comp_sd(_ni), comp_sd(_nb), comp_sd(_nh)
    nF = np.array([np.abs(x).max() for x in _nf])
    nI = np.array([np.abs(x).max() for x in _ni])
    nB = np.array([np.abs(x).max() for x in _nb])
    nH = np.array([np.abs(x).max() for x in _nh])
    nF, nI, nB, nH = nF / kf, nI / ki, nB / kb, nH / kh
    sF, sI, sB, sH = maxes(5.0, INJ)
    sF, sI, sB, sH = sF / kf, sI / ki, sB / kb, sH / kh

    # harness check: bf16 must track float closely, or nothing below is real
    dev = float(np.std(sB - sF))
    assert dev < 0.05, "bf16 deviates by %.3f -- harness bug, not precision" % dev

    # Fix the false-dismissal rate at the budget and let each path move its
    # OWN gate to hit it; then the only remaining difference is what that
    # costs the fine stage in escalation. Matching float's observed
    # dismissal instead is unstable when it dismisses nothing: the gate
    # lands on the extreme tail and the comparison is pure noise.
    TARGET = 0.01
    out = []
    for nm, s_, n_ in (("float", sF, nF), ("int8", sI, nI), ("bf16", sB, nB), ("fp16", sH, nH)):
        t = float(np.quantile(s_, TARGET))
        out.append((nm, t, float((n_ >= t).mean())))
    esc_f = out[0][2]
    print("clip %.0f sigma | gate each path needs for %.0f%% dismissal at coarse SNR 5"
          % (KSIG, 100 * TARGET))
    for nm, t, e in out:
        print("   %-5s gate %.3f -> noise escalation %.4f  (%.2fx float)"
              % (nm, t, e, (e / esc_f) if esc_f else float("nan")))
    print("   int8 peak error vs float: mean %+.4f sd %.4f | bf16 sd %.4f | fp16 sd %.4f"
          % (float((sI - sF).mean()), float((sI - sF).std()), dev, float(np.std(sH - sF))))
