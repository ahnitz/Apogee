// Textually shared transform body. Keeping it in the caller preserves the
// full-precision kernel's compiler/inlining behavior and register allocation.
#ifndef RADIX
#define RADIX 16
#endif
#define FFT_LOG_RADIX ((RADIX == 16) ? 4u : ((RADIX == 32) ? 5u : 6u))
    [ForceUnroll] for (uint lvl = 0; lvl < NLEVELS; ++lvl) {
        uint want[RADIX];                       // scoped per level
        [unroll] for (uint z = 0; z < R; ++z) want[z] = 0u;
        // lvl is an unrolled constant, so all of these are constants
        const uint TB   = WG >> (FFT_LOG_RADIX * lvl);
        const uint len  = N  >> (FFT_LOG_RADIX * lvl);
        const uint lgTB = firstbithigh(TB);
        const uint lgLn = firstbithigh(len);
        uint blk  = tid >> lgTB;
        uint lane = tid & (TB - 1);

#if RADIX == 16
        dft16(r);
#else
        dftR(r);
#endif
        // Same recurrence as the SoA path: w_k = w_1^k, so one cos/sin per
        // level rather than sixteen. Every band except 512 runs THIS path,
        // so leaving it here would have confined the saving to one band.
        {
            float a1 = 2.0f * PI * float(lane) / float(len);
            float wr = cos(a1), wi = sin(a1);
            float cr = 1.0f, ci = 0.0f;
            [unroll] for (uint k2 = 0; k2 < R; ++k2) {
                r[k2] = cmul(r[k2], C(CS(cr), CS(ci)));
                float nr = cr * wr - ci * wi;
                ci = cr * wi + ci * wr;
                cr = nr;
            }
        }

        // one assignment of want[], then one call: the branchy version
        // left the compiler unsure it was initialised on every path
        const uint per  = R / max(TB, 1u);
        const uint TB2  = max(TB >> FFT_LOG_RADIX, 1u), len2 = TB;
        uint blk2 = tid / TB2, lane2 = tid % TB2;
        [unroll] for (uint d = 0; d < R; ++d) {
            uint j = d / max(TB, 1u), m = d % max(TB, 1u);
            want[d] = (TB <= R) ? (blk * len + (lane * per + j) * TB + m)
                                : (blk2 * len2 + lane2 + TB2 * d);
        }
        exchange(r, want, lgLn, lgTB);
    }
    const uint INNER_TB = WG >> (FFT_LOG_RADIX * (NLEVELS - 1));
    innermost(r);

#undef FFT_LOG_RADIX
