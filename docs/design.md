# Batched matched filter: design

D data segments and T template segments arrive as spectra: complex vectors of
length N, the unnormalised forward transform of each segment. For every pair the
output is

    z_dt[k] = IFFT( D_d[f] * conj(H_t[f]) )[k]

reported as a binned maximum over a search window, with a detection floor.
D and T are arbitrary.

## Where the time goes

Forward transforms number D+T. Pair work is D*T. At D=T=16 the pair loop is
~89% of the work before any optimisation, so every design decision is made about
the pair loop.

Per pair, done naively:

    read D_d           N complex
    read H_t           N complex
    write product P    N complex
    read P             N complex     <- IFFT stage A
    write intermediate N complex
    read intermediate  N complex

At 2^20 that is 48 MiB per pair, and 256 pairs is 12 GiB.

## What reuse buys

1. **Fuse the product into the IFFT's stage-A load.** The product never has to
   exist in memory: stage A reads `D_d` and `H_t` and multiplies on the way in.
   Removes 2 of the 6 passes, 16 MiB of 48 per pair.

2. **Pre-permute the stored spectra into stage-A order.** Stage A reads
   `x[n2*N1 + n1]` walking n2, i.e. with stride N1, measured at 7.6 GB/s against
   43.9 sequential on this core. Storing the spectra as `X'[n1*N2 + n2]` makes
   that read contiguous. The permutation costs one transpose per segment (D+T of
   them) instead of a strided read per pair (D*T of them): at D=T=16, 32
   transposes to avoid 256 strided passes.

3. **Cache-block the (d,t) loop.** The matmul argument: a tile of nd×nt pairs
   loads nd+nt spectra and does nd*nt work, so traffic falls by roughly the
   harmonic mean where the spectra fit.

4. **Conjugate templates once at ingest**, not per pair.

![A square tile reuses eight input spectra for sixteen pairs; a strip needs seventeen.](assets/pair-tiles.svg)

The diagram counts distinct inputs, not compulsory DRAM transfers: cache
capacity and loop order determine the actual traffic. This cache tile is
separate from SIMD pair batching, which currently fills lanes with templates
for one data segment. A 32×1 batch therefore does not fill 32 SIMD lanes.

## What does not work, and why

- **Pushing butterflies across the product.** The product is elementwise in
  frequency and butterflies mix frequencies, so no part of the IFFT can be
  pre-applied to `D` or `H` separately. Only the *permutation* commutes with an
  elementwise product, which is why (2) works and a pre-butterflied store does
  not.
- **Sharing IFFT work between pairs.** Different pairs have different inputs;
  there is no common subexpression beyond what (1) to (3) already capture.

## Why the input is frequency domain

Taking time-domain segments would let the ingest rearrangement fuse into a
forward transform the library performed itself, making it free. Measured, that
rearrangement is only 1.9 to 4.5% of total, and shrinks as T grows:

| N | D × T | ingest | pair loop | share |
|---|---|---:|---:|---:|
| 2^12 | 16×16 | 26.7 µs | 652 µs | 3.9% |
| 2^12 | 16×256 | 228 µs | 11566 µs | 1.9% |
| 2^14 | 16×16 | 104 µs | 2940 µs | 3.4% |
| 2^16 | 16×64 | 2470 µs | 55566 µs | 4.3% |

Owning the forward transform is not worth that, and the caller's pipeline
generally has the spectra already.
