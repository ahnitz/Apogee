#!/usr/bin/env python3
"""The transform decomposition, in Python, before it is written in Slang.

Every GPU bug found so far was silent -- a gather/scatter race, a
wave-width assumption, a buffer overrun -- and none would have failed a
benchmark. Two of the three were caught by checking peak indices against a
float64 reference; this file exists so the third class, an index or
twiddle mistake in the decomposition itself, is caught before it reaches a
kernel at all.

A length-L inverse transform carried by TB threads, each holding 16 points
in registers:

    L = TB * 16
    step 1   each thread does a 16-point DFT over its stride-TB column
    step 2   twiddle by W_L^(n1*k2)
    step 3   transpose, so each k2 block is contiguous
    step 4   a TB-point transform per block, carried by TB/16 threads

Step 4 recurses until TB <= 16, where one thread holds the whole block and
does it with no exchange at all.

Verified for every length one workgroup can carry:

    n       threads   recursion      max err
    1024        64    64->4          5.1e-14
    2048       128    128->8         7.8e-14
    4096       256    256->16        1.1e-13
    8192       512    512->32->2     2.3e-13
    16384     1024    1024->64->4    2.9e-13

n >= 32768 needs threads > 1024, so it is Tier C: either more points per
thread, or the four-step across dispatches with global memory between.
"""
import numpy as np


def four_step(x, TB):
    L = TB * 16
    assert len(x) == L, (len(x), L)
    A = np.zeros((TB, 16), complex)
    for n1 in range(TB):
        A[n1] = np.fft.ifft(x[n1::TB]) * 16          # step 1
    for n1 in range(TB):
        for k2 in range(16):
            A[n1, k2] *= np.exp(2j * np.pi * n1 * k2 / L)   # step 2
    out = np.zeros(L, complex)
    for k2 in range(16):                              # steps 3 and 4
        col = A[:, k2]
        sub = np.fft.ifft(col) * TB if TB <= 16 else four_step(col, TB // 16)
        for k1 in range(TB):
            out[k1 * 16 + k2] = sub[k1]
    return out


def chain(n):
    """The recursion a given length unrolls into."""
    out, t = [], n // 16
    while t > 16:
        out.append(t)
        t //= 16
    out.append(t)
    return out


if __name__ == "__main__":
    print("%-8s %-8s %-14s %-10s %s" % ("n", "threads", "recursion", "max err", ""))
    for n in (1024, 2048, 4096, 8192, 16384):
        TB = n // 16
        x = (np.random.default_rng(0).standard_normal(n)
             + 1j * np.random.default_rng(1).standard_normal(n))
        err = np.abs(four_step(x, TB) - np.fft.ifft(x) * n).max()
        print("%-8d %-8d %-14s %-10.1e %s"
              % (n, TB, "->".join(map(str, chain(n))), err,
                 "OK" if err < 1e-9 else "WRONG"))
    for n in (32768, 65536, 1048576):
        print("%-8d %-8d %-14s %s" % (n, n // 16, "-", "Tier C: over 1024 threads"))
