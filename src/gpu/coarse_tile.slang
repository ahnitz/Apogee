// Coarse pass, TILE pairs per workgroup.
//
// The coarse transform is short -- band is 256 to 2048 -- so one pair per
// workgroup gives WG = band/16, which is 16 THREADS at band=256: half a
// wave, with the other half idle, times one workgroup per pair. That is why
// the coarse pass ran at 17x a CPU core where the full transform runs at 53x.
//
// Here a workgroup carries TILE independent transforms side by side, each on
// its own TP = band/16 lanes, sharing one launch and filling the wave.
//
// TILE is 4, giving a 64-thread workgroup, because that measured fastest:
//
//     TILE      2      4      8     16     32
//     WG       32     64    128    256    512
//     ms    0.218  0.212  0.244  0.253  0.290     (untiled: 0.380)
//
// The same occupancy story as the exchange staging -- past 8 KB of shared
// memory the resident workgroup count falls and takes the throughput with
// it.
//
// RE-TESTED after the refine was compacted, because that sweep was taken
// when the refine spent 1.4 ms launching a workgroup per pair to have it
// exit, which could have swamped it. It did not: at 512x512 and n=4096,
// TILE 4 gives 1.757 ms against 2.113 at 8 and 1.931 at 16. Launching
// fewer workgroups is worth real time -- untiled costs 0.56 ms more than
// tiled here -- but occupancy pushes back harder past TILE 4, so this is
// the optimum and not an artefact of what used to dominate.
#ifndef NBAND
#define NBAND 256
#endif
#ifndef TILE
#define TILE 4
#endif
static const uint BAND = NBAND;

//: A four-step of BAND = TP * R: each lane holds R points, TP lanes carry
//: one transform. Stage one is a length-R DFT down the registers, stage two
//: -- after the transpose -- is a length-TP DFT.
//:
//: Both stages being dft16 is what used to pin this kernel to BAND=256,
//: because that is the only band where TP and R are both 16. The failure at
//: any other band was a 24% error rather than a crash: the second stage
//: transformed 16 points where the axis was 32 long, which is a plausible
//: looking number.
//:
//: R is chosen per band so that both stages are a size this file implements:
//:
//:     BAND    256     512    1024
//:     R        16      32      32
//:     TP       16      16      32
//:     stages  16,16   32,16   32,32
//:
//: R beyond 32 is not offered. R float2 registers are 2R VGPRs of live data
//: per lane, and at R=64 that alone is 128 -- the occupancy this kernel
//: exists to buy back would go straight out again.
#ifndef RPT
#define RPT 16
#endif
static const uint R    = RPT;
static const uint TP   = BAND / R;           // lanes per transform
static const uint WG   = TP * TILE;
static const float PI  = 3.14159265358979f;

groupshared float2 sh[TILE * NBAND];

float2 cmul(float2 a, float2 b) { return float2(a.x*b.x - a.y*b.y, a.x*b.y + a.y*b.x); }
float2 cmulConj(float2 a, float2 b) { return float2(a.x*b.x + a.y*b.y, a.y*b.x - a.x*b.y); }

void r4(inout float2 a, inout float2 b, inout float2 c, inout float2 d)
{
    float2 t0=a+c, t1=a-c, t2=b+d, t3=b-d;
    float2 j3 = float2(-t3.y, t3.x);
    a=t0+t2; b=t1+j3; c=t0-t2; d=t1-j3;
}
void dft16(inout float2 r[16])
{
    const float2 W1=float2( 0.92387953f, 0.38268343f);
    const float2 W2=float2( 0.70710678f, 0.70710678f);
    const float2 W3=float2( 0.38268343f, 0.92387953f);
    const float2 W4=float2( 0.0f,        1.0f       );
    const float2 W6=float2(-0.70710678f, 0.70710678f);
    const float2 W9=float2(-0.92387953f,-0.38268343f);
    [unroll] for (uint n1=0;n1<4;++n1) r4(r[n1],r[n1+4],r[n1+8],r[n1+12]);
    r[5]=cmul(r[5],W1);  r[9]=cmul(r[9],W2);   r[13]=cmul(r[13],W3);
    r[6]=cmul(r[6],W2);  r[10]=cmul(r[10],W4); r[14]=cmul(r[14],W6);
    r[7]=cmul(r[7],W3);  r[11]=cmul(r[11],W6); r[15]=cmul(r[15],W9);
    [unroll] for (uint k2=0;k2<4;++k2) r4(r[4*k2],r[4*k2+1],r[4*k2+2],r[4*k2+3]);
    float2 t;
    t=r[1];  r[1]=r[4];   r[4]=t;
    t=r[2];  r[2]=r[8];   r[8]=t;
    t=r[3];  r[3]=r[12];  r[12]=t;
    t=r[6];  r[6]=r[9];   r[9]=t;
    t=r[7];  r[7]=r[13];  r[13]=t;
    t=r[11]; r[11]=r[14]; r[14]=t;
}

//: A 32-point DFT by decimation in time: split even and odd, one dft16 on
//: each, then combine with the 32nd roots. Reusing dft16 rather than writing
//: a second butterfly network keeps one implementation of the hard part.
//:
//: PLUS in the exponent, because dft16 above is the INVERSE convention --
//: r4 multiplies by +i and its twiddles are e^{+i pi/8}. Writing the
//: textbook e^{-2 pi i k/N} here produced a wrong answer that still looked
//: like a correlation magnitude: 19% low at band 512, 24% high at 1024.
void dft32(inout float2 r[32])
{
    float2 e[16], o[16];
    [unroll] for (uint i=0;i<16;++i) { e[i]=r[2*i]; o[i]=r[2*i+1]; }
    dft16(e);
    dft16(o);
    [unroll] for (uint k=0;k<16;++k) {
        float ang = 2.0f*PI*float(k)/32.0f;
        float2 w  = cmul(o[k], float2(cos(ang), sin(ang)));
        r[k]    = e[k] + w;
        r[k+16] = e[k] - w;
    }
}

//: Stage one: one length-R transform down each lane's registers.
void dftR(inout float2 r[R])
{
#if RPT == 16
    dft16(r);
#else
    dft32(r);
#endif
}

//: Stage two: R/TP transforms of length TP, on consecutive chunks of the
//: registers. The transpose leaves lane L holding rows L*(R/TP) onward of
//: the R x TP array, each row TP long and contiguous -- so the chunking is
//: just r[0..TP), r[TP..2TP), and the read index sh[base + lane*R + i] that
//: produces it is the same expression at every band.
void stage2(inout float2 r[R])
{
#if RPT == 16
    dft16(r);                                   // BAND=256:  one 16
#elif (NBAND / RPT) == 16
    {                                           // BAND=512:  two 16s
        float2 a[16];
        [unroll] for (uint q=0;q<16;++q) a[q] = r[q];
        dft16(a);
        [unroll] for (uint q=0;q<16;++q) r[q] = a[q];
        [unroll] for (uint q=0;q<16;++q) a[q] = r[16+q];
        dft16(a);
        [unroll] for (uint q=0;q<16;++q) r[16+q] = a[q];
    }
#else
    dft32(r);                                   // BAND=1024: one 32
#endif
}

//: Only the MAXIMUM magnitude is wanted, and a maximum is independent of the
//: output ordering -- so this needs no digit-reversal and no index.
[shader("compute")][numthreads(WG,1,1)]
void coarseTile(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
                StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
                RWStructuredBuffer<float2> out,
                uniform uint ntmpl, uniform uint npairs)
{
    uint tid = lid.x, slot = tid / TP, lane = tid % TP;
    uint pair = gid.x * TILE + slot;
    uint base = slot * BAND;
    if (pair >= npairs) return;
    uint d = pair / ntmpl, t = pair % ntmpl;

    float2 r[R];
    [unroll] for (uint i=0;i<R;++i) {
        uint k = lane + TP*i;
        r[i] = cmulConj(data[d*BAND + k], tmpl[t*BAND + k]);
    }
    dftR(r);
    [unroll] for (uint k2=0;k2<R;++k2) {
        float ang = 2.0f*PI*float(lane*k2)/float(BAND);
        r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
    }
    // Transpose through the tile's own slice of shared memory.
    GroupMemoryBarrierWithGroupSync();
    [unroll] for (uint i=0;i<R;++i) sh[base + i*TP + lane] = r[i];
    GroupMemoryBarrierWithGroupSync();
    [unroll] for (uint i=0;i<R;++i) r[i] = sh[base + lane*R + i];
    stage2(r);

    float best = 0.0f;
    [unroll] for (uint i=0;i<R;++i) best = max(best, r[i].x*r[i].x + r[i].y*r[i].y);
    // Reduce the slot's TP lanes. TP <= 128 and slots never straddle a wave
    // boundary while TP divides the wave width, so a shared-memory reduce is
    // used rather than wave intrinsics, which would assume that.
    GroupMemoryBarrierWithGroupSync();
    sh[base + lane] = float2(best, 0.0f);
    GroupMemoryBarrierWithGroupSync();
    for (uint st = TP/2; st > 0; st >>= 1) {
        if (lane < st) sh[base+lane] = float2(max(sh[base+lane].x, sh[base+lane+st].x), 0.0f);
        GroupMemoryBarrierWithGroupSync();
    }
    // Written as float2(magnitude, 0) so the gated kernels can read this
    // and the general coarse kernel's output through the same binding --
    // length() of either gives the magnitude, and one gated kernel serves
    // both paths.
    if (lane == 0) out[pair] = float2(sqrt(sh[base].x), 0.0f);
}
