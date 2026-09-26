#!/usr/bin/env python3
"""Tier C: the lengths one workgroup cannot carry, split across dispatches.

Tier B carries a whole transform in one workgroup, so n = WG * R with WG
capped at 1024 threads.  R=64 reaches 65536 and stops: R=128 would be 256
VGPRs of transform state per thread before any working set.  The CPU goes
to 1048576, so four lengths -- 131072, 262144, 524288, 1048576 -- need the
four-step split across dispatches with global memory between.

This file is the decomposition, checked against a float64 reference before
any of it is written in Slang, exactly as gpu_regmodel.py was for Tier B.
It exists because the kernel's failure mode is a peak reported at the wrong
SAMPLE: magnitudes stay plausible, benchmarks stay fast, and only an index
comparison notices.

    n = N1 * N2,  j = n1 + N1*n2,  k = k1*N2 + k2

    stage 1   for each n1:  an N2-point transform over n2 of x[n1 + N1*n2]
    stage 2   multiply by W_n^(n1*k2)           -- fused into stage 1
    stage 3   for each k2:  an N1-point transform over n1
    output    X[k1*N2 + k2] = stage3[k2][k1]

Both factors land at 1024 or below, which is a length Tier B already
carries -- so the sub-transforms are the existing kernel geometry and only
the addressing is new.

    n          N1     N2
    131072     256    512
    262144     512    512
    524288     512    1024
    1048576    1024   1024

The scratch buffer is stored TRANSPOSED, A[k2*N1 + n1].  That makes stage 1
scatter with stride N1 and stage 3 read contiguously.  One of the two is
strided either way; putting it on the write side is the cheaper half,
because stage 3's read feeds a transform that would otherwise serialise on
it.

What is NOT modelled here, and is the remaining work:

  * the peak reduction is per workgroup in Tier B and must become GLOBAL --
    stage 3 spreads one pair's output across N2 workgroups, so the per-bin
    maximum needs an atomic table in device memory and a second pass to
    write the index and value that match it.  The float-bits-as-uint
    monotone trick the LDS path uses carries over unchanged.
  * the scratch buffer is n complex per pair IN FLIGHT: 8 MB a pair at
    1048576, so pairs have to be chunked rather than dispatched at once.
  * Tier B leaves each sub-transform digit-reversed within itself, so both
    stages need slotToIndex applied before their results are placed --
    stage 1 on k2, stage 3 on k1.  That is the part this model pins.
"""
import numpy as np

from gpu_regmodel import geom, registers, slot_to_index

PI = np.pi


def split(n):
    """N2 inner, N1 outer. Balanced, and both must be Tier B lengths."""
    n2 = 1
    while n2 * n2 * 2 <= n:
        n2 *= 2
    return n // n2, n2


def tierc(x, n):
    N1, N2 = split(n)
    A = np.zeros(n, complex)                      # A[k2*N1 + n1], transposed
    for n1 in range(N1):
        a = np.fft.ifft(x[n1::N1]) * N2           # stage 1
        for k2 in range(N2):
            A[k2 * N1 + n1] = a[k2] * np.exp(2j * PI * n1 * k2 / n)   # stage 2
    out = np.zeros(n, complex)
    for k2 in range(N2):
        b = np.fft.ifft(A[k2 * N1:(k2 + 1) * N1]) * N1                # stage 3
        for k1 in range(N1):
            out[k1 * N2 + k2] = b[k1]
    return out


def tierc_kernels(x, n, R=16):
    """The same split, but through the REAL sub-transform.

    tierc() above checks the decomposition. This checks the thing the
    kernel will actually do: each stage is a Tier B transform, which
    leaves its output digit-reversed in registers, so `slot_to_index`
    applies TWICE -- on k2 leaving stage 1 and on k1 leaving stage 3.

    That double application is the part with no safety net. A magnitude
    is order-independent, so getting either one wrong reports a real peak
    at the wrong sample and nothing else notices. Pinning it here is why
    the kernel can be written from this file rather than debugged into
    existence.
    """
    N1, N2 = split(n)

    # stage 1: one workgroup per (pair, n1), transform length N2
    WG2, NL2, IN2 = geom(N2, R)
    lg2 = int(np.log2(R))
    A = np.zeros(n, complex)
    for n1 in range(N1):
        reg = registers(x[n1::N1], N2, R)
        for tid in range(WG2):
            for q in range(R):
                k2 = slot_to_index(tid * R + q, NL2, IN2, lg2)
                A[k2 * N1 + n1] = reg[tid][q] * np.exp(2j * PI * n1 * k2 / n)

    # stage 3: one workgroup per (pair, k2), transform length N1
    WG1, NL1, IN1 = geom(N1, R)
    lg1 = int(np.log2(R))
    out = np.zeros(n, complex)
    for k2 in range(N2):
        reg = registers(A[k2 * N1:(k2 + 1) * N1], N1, R)
        for tid in range(WG1):
            for q in range(R):
                k1 = slot_to_index(tid * R + q, NL1, IN1, lg1)
                out[k1 * N2 + k2] = reg[tid][q]
    return out


#: The lengths the CPU covers and Tier B does not.
CASES = (131072, 262144, 524288, 1048576)


if __name__ == "__main__":
    rng = np.random.default_rng(1)
    print("%-9s %-6s %-6s %-9s" % ("n", "N1", "N2", "rel err"))
    bad = 0
    for n in CASES:
        N1, N2 = split(n)
        x = rng.standard_normal(n) + 1j * rng.standard_normal(n)
        ref = np.fft.ifft(x) * n
        err = np.abs(tierc(x, n) - ref).max() / np.abs(ref).max()
        ok = err < 1e-12
        bad += not ok
        print("%-9d %-6d %-6d %-9.1e %s" % (n, N1, N2, err, "OK" if ok else "WRONG"))

    #: Through the real sub-transform, at the smallest case only -- the
    #: index contract is structural, not length-dependent, and the larger
    #: ones cost minutes in a Python loop for no extra coverage.
    n = CASES[0]
    x = rng.standard_normal(n) + 1j * rng.standard_normal(n)
    ref = np.fft.ifft(x) * n
    err = np.abs(tierc_kernels(x, n) - ref).max() / np.abs(ref).max()
    ok = err < 1e-12
    bad += not ok
    print("\nthrough the real Tier B sub-transform (slot_to_index applied twice):")
    print("%-9d %-6s %-6s %-9.1e %s" % (n, "", "", err, "OK" if ok else "WRONG"))
    raise SystemExit(1 if bad else 0)
