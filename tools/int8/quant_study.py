"""Does INT8 survive the coarse stage?

Models the pipeline the Monarch spec describes, not just a rounded input:
the band product is quantised to int8, the two Monarch sub-transforms use
int8 DFT matrices with int32 accumulation, and the intermediate is
requantised to int8 between stages (that requantisation is the step people
forget -- int32 cannot feed the next int8 matrix op).

Integer arithmetic is modelled in float64 with explicit round/clip. That is
exact as long as the int32 accumulator cannot overflow, which the spec
argues and which we assert here rather than assume.
"""
import numpy as np

N, BAND = 4096, 512
N1, N2 = 16, 32                      # BAND = N1 * N2
assert N1 * N2 == BAND


def q8(x, s):
    return np.clip(np.round(x * s), -127.0, 127.0)


def bf16(x):
    """Round-to-nearest-even bfloat16, via the float32 bit pattern."""
    a = np.asarray(x, np.float32).view(np.uint32)
    r = ((a >> 16) & 1) + 0x7FFF
    return ((a + r) & 0xFFFF0000).view(np.float32)


def reference_power(n, rng):
    k = np.arange(1, n // 2)
    p = np.zeros(n)
    p[1:n // 2] = k ** (-7 / 3.0) / ((0.015 * n / k) ** 4 + 1.0)
    return p / p.sum()


def whitened_product(n, band, power, rng, inject=0.0):
    """P[k] = d_w conj(h_w) over the coarse band, plus an optional signal.

    Both sides are whitened, so P has flat variance -- which is the spec's
    justification for a STATIC scale, and the thing being tested.
    """
    S = np.where(power > 0, power, power[power > 0].min())
    h = np.zeros(n, np.complex128)
    kk = np.arange(1, n // 2)
    h[1:n // 2] = ((0.5 + rng.uniform(0, 1, kk.size))
                   * np.exp(2j * np.pi * rng.uniform(0, 1, kk.size)))
    hw = h / np.sqrt(S)
    hw /= np.linalg.norm(hw)

    d = (rng.normal(size=n) + 1j * rng.normal(size=n)) / np.sqrt(2.0)
    dw = d.copy()
    if inject:
        lag = int(rng.integers(0, band))
        # hw, NOT conj(hw): the product below is d*conj(h), so the signal
        # has to enter as h for that product to become |hw|^2 and sum
        # COHERENTLY across bins. Injecting conj(hw) makes the product
        # conj(hw)^2, whose phase still winds -- it never builds a peak, so
        # every injection looked like noise and the study measured nothing.
        # Scale to the energy the COARSE BAND actually sees. Only part of a
        # broadband template's power lies below `band`, so a nominal SNR 6
        # arrives at the coarse stage as 6*sqrt(that fraction) -- about 3
        # here, under the 4.343 gate. Injecting nominally meant the only
        # "detections" were marginal noise-luck cases sitting on the
        # threshold, which ANY perturbation flips: bf16 then looked like it
        # lost 70% of them, which is a statement about the harness.
        w = float(np.sqrt(np.sum(np.abs(hw[:band]) ** 2)))
        dw += (inject / w) * hw * np.exp(-2j * np.pi * np.arange(n) * lag / n)
    P = (dw * np.conj(hw))[:band]
    return P


def rho_float(P):
    return np.fft.ifft(P) * P.size


def rho_monarch_int8(P, sp, sw, srq):
    """Four-step/Monarch BAND-point transform in int8 -> int32.

    stage 1 : (N1,N2) x W_N2   int8 x int8 -> int32
    requant : int32 -> int8                (spec omits it; it is mandatory)
    twiddle : int8 x int8 -> int32
    stage 2 : W_N1 x (N1,N2)   int8 x int8 -> int32
    """
    # A[n1][n2] = x[n2*N1 + n1]. The obvious reshape(N1, N2) is the WRONG
    # decimation for the four-step and it is dangerously close to right:
    # the peak magnitude lands within a few percent of the true one, so it
    # reads as a precision effect instead of a broken transform.
    x = P.reshape(N2, N1).T
    xr, xi = q8(x.real, sp), q8(x.imag, sp)

    j2 = np.outer(np.arange(N2), np.arange(N2))
    w2 = np.exp(2j * np.pi * j2 / N2)          # inverse transform sign
    w2r, w2i = q8(w2.real, sw), q8(w2.imag, sw)

    yr = xr @ w2r - xi @ w2i                   # int32
    yi = xr @ w2i + xi @ w2r
    peak32 = max(np.abs(yr).max(), np.abs(yi).max())

    yr, yi = q8(yr, srq), q8(yi, srq)          # back to int8

    n1 = np.arange(N1)[:, None]
    k2 = np.arange(N2)[None, :]
    tw = np.exp(2j * np.pi * n1 * k2 / BAND)
    tr, ti = q8(tw.real, sw), q8(tw.imag, sw)
    zr = yr * tr - yi * ti
    zi = yr * ti + yi * tr
    zr, zi = q8(zr, srq), q8(zi, srq)

    j1 = np.outer(np.arange(N1), np.arange(N1))
    w1 = np.exp(2j * np.pi * j1 / N1)
    w1r, w1i = q8(w1.real, sw), q8(w1.imag, sw)
    orr = w1r @ zr - w1i @ zi
    oi = w1r @ zi + w1i @ zr
    peak32 = max(peak32, np.abs(orr).max(), np.abs(oi).max())
    assert peak32 < 2 ** 31, f"int32 overflow: {peak32:.3g}"
    return (orr + 1j * oi).ravel(), peak32


def _f16(x):
    return np.asarray(x, np.float16).astype(np.float32)


def rho_fp16(P):
    """Same pipeline in fp16. For a WHITENED product -- flat variance,
    bounded range -- fp16's 10 mantissa bits strictly beat bf16's 7, and
    range is a non-issue precisely because the product is whitened."""
    x = P.reshape(N2, N1).T
    xr, xi = _f16(x.real), _f16(x.imag)
    j2 = np.outer(np.arange(N2), np.arange(N2))
    w2 = np.exp(2j * np.pi * j2 / N2)
    w2r, w2i = _f16(w2.real), _f16(w2.imag)
    yr = _f16(xr @ w2r - xi @ w2i); yi = _f16(xr @ w2i + xi @ w2r)
    n1 = np.arange(N1)[:, None]; k2 = np.arange(N2)[None, :]
    tw = np.exp(2j * np.pi * n1 * k2 / BAND)
    tr, ti = _f16(tw.real), _f16(tw.imag)
    zr = _f16(yr * tr - yi * ti); zi = _f16(yr * ti + yi * tr)
    j1 = np.outer(np.arange(N1), np.arange(N1))
    w1 = np.exp(2j * np.pi * j1 / N1)
    w1r, w1i = _f16(w1.real), _f16(w1.imag)
    orr = _f16(w1r @ zr - w1i @ zi); oi = _f16(w1r @ zi + w1i @ zr)
    return (orr + 1j * oi).ravel()


def rho_bf16(P):
    # A[n1][n2] = x[n2*N1 + n1]. The obvious reshape(N1, N2) is the WRONG
    # decimation for the four-step and it is dangerously close to right:
    # the peak magnitude lands within a few percent of the true one, so it
    # reads as a precision effect instead of a broken transform.
    x = P.reshape(N2, N1).T
    xr, xi = bf16(x.real), bf16(x.imag)
    j2 = np.outer(np.arange(N2), np.arange(N2))
    w2 = np.exp(2j * np.pi * j2 / N2)
    w2r, w2i = bf16(w2.real), bf16(w2.imag)
    yr = bf16(xr @ w2r - xi @ w2i); yi = bf16(xr @ w2i + xi @ w2r)
    n1 = np.arange(N1)[:, None]; k2 = np.arange(N2)[None, :]
    tw = np.exp(2j * np.pi * n1 * k2 / BAND)
    tr, ti = bf16(tw.real), bf16(tw.imag)
    zr = bf16(yr * tr - yi * ti); zi = bf16(yr * ti + yi * tr)
    j1 = np.outer(np.arange(N1), np.arange(N1))
    w1 = np.exp(2j * np.pi * j1 / N1)
    w1r, w1i = bf16(w1.real), bf16(w1.imag)
    orr = bf16(w1r @ zr - w1i @ zi); oi = bf16(w1r @ zi + w1i @ zr)
    return (orr + 1j * oi).ravel()


def _self_test():
    """The decomposition must reproduce the exact IFFT at full precision.

    Without this the study measured a broken transform and attributed the
    error to the number format.
    """
    rng = np.random.default_rng(1)
    P = rng.normal(size=BAND) + 1j * rng.normal(size=BAND)
    ref = np.fft.ifft(P) * BAND
    A = P.reshape(N2, N1).T
    j2 = np.outer(np.arange(N2), np.arange(N2))
    B = A @ np.exp(2j * np.pi * j2 / N2)
    n1 = np.arange(N1)[:, None]; k2 = np.arange(N2)[None, :]
    C = B * np.exp(2j * np.pi * n1 * k2 / BAND)
    j1 = np.outer(np.arange(N1), np.arange(N1))
    X = np.exp(2j * np.pi * j1 / N1) @ C
    e = np.abs(X.ravel() - ref).max() / np.abs(ref).max()
    assert e < 1e-12, f"Monarch decomposition is wrong: rel err {e:.3e}"
    return e


_self_test()
