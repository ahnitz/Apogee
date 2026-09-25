//: DRAFT -- split/SoA dual-transform core for the coarse stage.
//: NOT WIRED IN. Replaces the C=half2 (re,im) core in tierb.slang.
//:
//: Every half2 here holds the SAME element of TWO INDEPENDENT transforms:
//:     re[i] = ( re of pair A element i , re of pair B element i )
//:     im[i] = ( im of pair A element i , im of pair B element i )
//: The two lanes never interact, so every operation below is elementwise
//: and lowers to v_pk_*. The AoS form could not: a complex multiply
//: (ax*bx - ay*by, ax*by + ay*bx) is a CROSS pattern, which is why the
//: shipped kernel emits 789 scalar half ops against 928 packed.
//:
//: Register cost is NEUTRAL: re[16]+im[16] for two transforms is 32 VGPRs,
//: exactly what two C r[16] cost today. TILE_T already supplies the two
//: independent transforms.

typedef half2 H;

//: Complex multiply by a twiddle that is the SAME for both transforms, so
//: wr/wi broadcast to both lanes. Four v_pk_* and nothing else.
void cmulw(inout H xr, inout H xi, CS wr, CS wi)
{
    H nr = xr * wr - xi * wi;
    H ni = xr * wi + xi * wr;
    xr = nr; xi = ni;
}

//: Correlate against a conjugated template: (ar,ai) * conj(br,bi).
//: Both lanes are distinct transforms, so this is fully packed too.
void cmulconjs(H ar, H ai, H br, H bi, out H pr, out H pi)
{
    pr = ar * br + ai * bi;
    pi = ai * br - ar * bi;
}

//: Radix-4 butterfly.
//:
//: The ×i rotation is the quiet win. AoS needed C(-t3.y, t3.x) -- a
//: cross-component swizzle, one of the v_mov_b16 the ISA dump is full of.
//: In SoA it is a register RENAME plus a negate, and radix-4 is built from
//: these: every ±i in the kernel becomes free.
void r4s(inout H re[16], inout H im[16], uint a, uint b, uint c, uint d)
{
    H t0r = re[a] + re[c], t0i = im[a] + im[c];
    H t1r = re[a] - re[c], t1i = im[a] - im[c];
    H t2r = re[b] + re[d], t2i = im[b] + im[d];
    H t3r = re[b] - re[d], t3i = im[b] - im[d];
    H j3r = -t3i, j3i = t3r;                 // i * t3, free
    re[a] = t0r + t2r; im[a] = t0i + t2i;
    re[b] = t1r + j3r; im[b] = t1i + j3i;
    re[c] = t0r - t2r; im[c] = t0i - t2i;
    re[d] = t1r - j3r; im[d] = t1i - j3i;
}

void swap2(inout H re[16], inout H im[16], uint p, uint q)
{
    H t;
    t = re[p]; re[p] = re[q]; re[q] = t;
    t = im[p]; im[p] = im[q]; im[q] = t;
}

void dft2s(inout H re[16], inout H im[16], uint o)
{
    H ar = re[o], ai = im[o], br = re[o+1], bi = im[o+1];
    re[o]   = ar + br; im[o]   = ai + bi;
    re[o+1] = ar - br; im[o+1] = ai - bi;
}

void dft4s(inout H re[16], inout H im[16], uint o)
{
    r4s(re, im, o, o+1, o+2, o+3);
    swap2(re, im, o+1, o+2);
}

void dft8s(inout H re[16], inout H im[16], uint o)
{
    H br[8], bi[8];
    [unroll] for (uint s = 1; s < 8; s <<= 1) {
        [unroll] for (uint j = 0; j < 4; ++j) {
            uint k = j & (s-1), base = (j-k) << 1;
            float ang = PI * float(k) / float(s);
            H vr = re[o+j+4], vi = im[o+j+4];
            cmulw(vr, vi, CS(cos(ang)), CS(sin(ang)));
            H ur = re[o+j], ui = im[o+j];
            br[base+k]   = ur + vr; bi[base+k]   = ui + vi;
            br[base+k+s] = ur - vr; bi[base+k+s] = ui - vi;
        }
        [unroll] for (uint i = 0; i < 8; ++i) { re[o+i] = br[i]; im[o+i] = bi[i]; }
    }
}

void dft16s(inout H re[16], inout H im[16])
{
    [unroll] for (uint n1 = 0; n1 < 4; ++n1) r4s(re, im, n1, n1+4, n1+8, n1+12);
    // Same twiddles as the AoS form, now broadcast scalars rather than
    // packed constants -- the multiply is elementwise in SoA.
    cmulw(re[5],  im[5],  CS( 0.92387953f), CS( 0.38268343f));  // W1
    cmulw(re[9],  im[9],  CS( 0.70710678f), CS( 0.70710678f));  // W2
    cmulw(re[13], im[13], CS( 0.38268343f), CS( 0.92387953f));  // W3
    cmulw(re[6],  im[6],  CS( 0.70710678f), CS( 0.70710678f));  // W2
    cmulw(re[10], im[10], CS( 0.0f),        CS( 1.0f));         // W4 = i
    cmulw(re[14], im[14], CS(-0.70710678f), CS( 0.70710678f));  // W6
    cmulw(re[7],  im[7],  CS( 0.38268343f), CS( 0.92387953f));  // W3
    cmulw(re[11], im[11], CS(-0.70710678f), CS( 0.70710678f));  // W6
    cmulw(re[15], im[15], CS(-0.92387953f), CS(-0.38268343f));  // W9
    [unroll] for (uint k2 = 0; k2 < 4; ++k2)
        r4s(re, im, 4*k2, 4*k2+1, 4*k2+2, 4*k2+3);
    swap2(re, im, 1, 4);   swap2(re, im, 2, 8);   swap2(re, im, 3, 12);
    swap2(re, im, 6, 9);   swap2(re, im, 7, 13);  swap2(re, im, 11, 14);
}

//: |v|^2 for BOTH transforms in one packed multiply-add. The shipped
//: kernel promotes to fp32 here (float(r[i].x) etc), which is 598 of the
//: fp32 ops in the ISA dump; this keeps it in half and hands back one
//: magnitude per lane.
H mag2s(H re, H im) { return re * re + im * im; }

//: REMAINING WORK to wire this in (must land atomically -- an AoS/SoA
//: boundary costs exactly the gather/scatter being eliminated):
//:   1. exchange(): stage re[] and im[] as two half2 regions, or one
//:      region of doubled stride. Keep adjacent lanes on adjacent
//:      addresses -- coalescing beat instruction count twice already.
//:   2. filterOne(): take (re,im) arrays, drive TWO pairs per call, and
//:      write two peaks. TILE_T=4 becomes two calls rather than four.
//:   3. the load: cload two rows into (re,im) lanes directly.
//:   4. the peak: mag2s gives both lanes; reduce per lane, and keep the
//:      per-tile InterlockedMax into stg[_stgBase] -- a wave-wide reduce
//:      would mix the two transforms, which is the PPG bug again.
//: Verify with RADV_DEBUG=shaderstats (expect VGPR ~unchanged) and
//: RADV_DEBUG=asm (expect scalar v_*_f16 near zero).
