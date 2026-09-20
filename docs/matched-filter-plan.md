# Batched matched filter: design and test plan

## The problem

D data segments and T template segments, all complex vectors of length N.  For
every pair we want the matched-filter output

    z_dt[k] = IFFT( D_d[f] * conj(H_t[f]) )[k]

and then the same peak report we already produce: binned maximum over a window,
with a detection floor.  D=T=16 for testing; the code must take arbitrary D, T.

## Where the time goes

Forward transforms are D+T = 32.  Pair work is D*T = 256.  So the pair loop is
~89% of the transforms before any optimisation, and every design decision should
be made about the pair loop.

Per pair, done naively:

    read D_d          N complex
    read H_t          N complex
    write product P   N complex
    read P            N complex      <- IFFT stage A
    write intermediate N complex
    read intermediate  N complex
    (no output: binned max only)

At 2^20 that is 48 MiB per pair, and 256 pairs is 12 GiB.

## What reuse buys, in order of expected value

1. **Fuse the product into the IFFT's stage-A load.**  The product never has to
   exist in memory: stage A reads D_d and H_t and multiplies on the way in.
   Removes 2 of the 6 passes - 16 MiB of 48 per pair.

2. **Pre-permute the stored spectra into stage-A order.**  This is the big one and
   it is what reuse unlocks.  Stage A reads `x[n2*N1 + n1]` walking n2, i.e. with
   stride N1 - measured at 7.6 GB/s against 43.9 sequential on this core.  If the
   spectra are *stored* as `X'[n1*N2 + n2]`, stage A reads contiguously.  The
   permutation costs one transpose per segment (D+T of them) instead of a strided
   read per pair (D*T of them).  At D=T=16 that is 32 transposes to save 256
   strided passes.

3. **Cache-block the (d,t) loop.**  Exactly the matmul argument: a tile of
   nd x nt pairs loads nd+nt spectra and does nd*nt work.  Reuse factor is the
   harmonic mean, so a 4x4 tile cuts spectrum traffic 4x where the spectra fit.

4. **Conjugate templates once at ingest**, not per pair.

5. **Threshold and window apply per pair** exactly as now, so all the binned-max
   work carries over unchanged.

## What does NOT work, and why (so it is not re-litigated)

- **Pushing butterflies across the product.**  Tempting, but the product is
  elementwise in frequency and butterflies mix frequencies, so no part of the IFFT
  can be pre-applied to D or H separately.  Only the *permutation* commutes with
  an elementwise product, which is why item 2 works and a "pre-butterflied" store
  does not.
- **Sharing IFFT work between pairs.**  Different pairs have different inputs;
  there is no common subexpression beyond what items 1-3 already capture.

## Test plan

Correctness, all against a double-precision reference computed independently:

1. **Single pair** - `pf_mf` with D=T=1 against an explicit
   `IFFT(FFT(d)*conj(FFT(h)))` in double.
2. **Every pair independently** - for D=T=16, all 256 outputs checked against
   their own reference, not just a spot check.
3. **Known answer** - template a circularly delayed copy of the data: the peak
   must be at exactly that lag, with magnitude equal to the data's energy.
4. **Linearity** - `z(a+b, h) == z(a,h) + z(b,h)` to fp32 tolerance.
5. **Reuse invariance** - duplicating a template (or a data segment) must produce
   bit-identical rows; this is what catches state leaking between pairs.
6. **Blocking invariance** - running any sub-block (d0,nd,t0,nt) must equal the
   corresponding slice of the full run.  Catches tiling bugs.
7. **Shape coverage** - (1,1), (1,16), (16,1), (3,5), (16,16), (17,13) so D!=T
   and non-power-of-two are both exercised.
8. **Window / threshold / bin size** - the same matrix `test_binmax` uses,
   including ragged final bins and non-aligned window starts.
9. **Empty result** - a floor above everything gives all bins `index = -1`.
10. **Accuracy** - worst relative error over all pairs < 1e-5 against double.

Performance:

- Baseline is the same computation built on MKL and on amd-fftw: forward
  transforms, elementwise product, inverse transforms, then a scan.  That is what
  a user would otherwise write, and it is the number to beat.
- Sweep N, D, T, bin size, window; report per-pair cost so shapes compare.
- Report **reuse efficiency**: per-pair cost as T grows with D fixed.  A flat line
  means reuse is working; a rising one means the tiling is wrong.
