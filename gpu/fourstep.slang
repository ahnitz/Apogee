// Register-resident four-step transform.
//
// The radix-4 Stockham pass goes through threadgroup memory once per
// stage: four stages at 256 points, four barriers, and eight complex
// moved through LDS per butterfly. Measurement says the coarse pass is
// not fetch-limited (see cache_probe.py), so that LDS traffic and those
// barriers are what is left to attack.
//
// This is the CPU's own decomposition. N = N1*N2; each thread holds one
// length-N1 sub-transform entirely in registers and does it with no
// barrier at all, the two halves meeting through a single transpose:
//
//   n = n1 + N1*n2     thread t owns n1 = t
//   step 1   DFT over n2 for each n1            -- in registers
//   step 2   multiply by W_N^(n1*k2)            -- in registers
//   step 3   transpose through LDS              -- ONE barrier
//   step 4   DFT over n1 for each k2            -- in registers
//
// At N=256 with N1=N2=16 that is one barrier against four, and the only
// LDS traffic is the transpose.

static const uint N1 = 16;
static const uint N2 = 16;
static const uint LEN = N1 * N2;             // 256
static const uint WG = 256;
static const uint TPT = 16;                  // threads per transform
static const uint SLOTS = WG / TPT;          // transforms in flight

groupshared float2 xchg[SLOTS * LEN];

float2 cmul(float2 a, float2 b) { return float2(a.x*b.x - a.y*b.y, a.x*b.y + a.y*b.x); }
float2 cmulConj(float2 a, float2 b) { return float2(a.x*b.x + a.y*b.y, a.y*b.x - a.x*b.y); }

// 16-point inverse DFT in registers, radix-4 x radix-4.
//
// The previous version was four radix-2 Stockham stages through a
// temporary, which costs 4 x 16 = 64 register moves per call on top of the
// arithmetic -- and this is called three times per 4096-point transform,
// per thread. Radix-4 twice has no temporary, two stages instead of four,
// and the twiddles are compile-time constants rather than sin/cos calls.
//
// Layout verified against numpy before being written here: step 1 does
// four length-4 DFTs over stride 4, the twiddle is W16^(n1*k2), step 2
// does four over contiguous groups, and the result lands at r[k1 + 4*k2]
// for X[k1][k2] -- a 4x4 transpose away from natural order, which is six
// swaps rather than sixteen moves.
void r4(inout float2 a, inout float2 b, inout float2 c, inout float2 d)
{
    float2 t0 = a + c, t1 = a - c, t2 = b + d, t3 = b - d;
    float2 jt3 = float2(-t3.y, t3.x);        // * +i, for the inverse
    a = t0 + t2; b = t1 + jt3; c = t0 - t2; d = t1 - jt3;
}

void dft16(inout float2 a[16])
{
    // W16^p = exp(+2*pi*i*p/16)
    const float2 W1 = float2( 0.92387953f,  0.38268343f);
    const float2 W2 = float2( 0.70710678f,  0.70710678f);
    const float2 W3 = float2( 0.38268343f,  0.92387953f);
    const float2 W4 = float2( 0.0f,         1.0f       );
    const float2 W6 = float2(-0.70710678f,  0.70710678f);
    const float2 W9 = float2(-0.92387953f, -0.38268343f);

    [unroll] for (uint n1 = 0; n1 < 4; ++n1)
        r4(a[n1], a[n1 + 4], a[n1 + 8], a[n1 + 12]);

    // A[n1][k2] *= W16^(n1*k2); n1=0 and k2=0 are identity
    a[1 + 4] = cmul(a[1 + 4], W1);  a[1 + 8] = cmul(a[1 + 8], W2);  a[1 + 12] = cmul(a[1 + 12], W3);
    a[2 + 4] = cmul(a[2 + 4], W2);  a[2 + 8] = cmul(a[2 + 8], W4);  a[2 + 12] = cmul(a[2 + 12], W6);
    a[3 + 4] = cmul(a[3 + 4], W3);  a[3 + 8] = cmul(a[3 + 8], W6);  a[3 + 12] = cmul(a[3 + 12], W9);

    [unroll] for (uint k2 = 0; k2 < 4; ++k2)
        r4(a[4*k2], a[4*k2 + 1], a[4*k2 + 2], a[4*k2 + 3]);

    // r[k1 + 4*k2] -> natural order r[k1*4 + k2]: a 4x4 transpose
    float2 t;
    t = a[1]; a[1] = a[4]; a[4] = t;
    t = a[2]; a[2] = a[8]; a[8] = t;
    t = a[3]; a[3] = a[12]; a[12] = t;
    t = a[6]; a[6] = a[9]; a[9] = t;
    t = a[7]; a[7] = a[13]; a[13] = t;
    t = a[11]; a[11] = a[14]; a[14] = t;
}

// One inverse transform of LEN points held at xchg[off .. off+LEN).
// `lane` in 0..TPT-1. Leaves the result in xchg.
void ifftReg(uint off, uint lane)
{
    float2 r[16];

    // step 1: this thread owns n1 = lane; gather its column, DFT over n2
    [unroll] for (uint n2 = 0; n2 < N2; ++n2) r[n2] = xchg[off + lane + N1 * n2];
    dft16(r);

    // step 2: twiddle by W_N^(n1*k2), still in registers
    [unroll] for (uint k2 = 0; k2 < N2; ++k2) {
        float ang = 2.0f * 3.14159265358979f * float(lane * k2) / float(LEN);
        r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
    }

    // step 3: the one transpose. A[n1][k2] -> xchg[k2*N1 + n1]
    [unroll] for (uint k2 = 0; k2 < N2; ++k2) xchg[off + k2 * N1 + lane] = r[k2];
    GroupMemoryBarrierWithGroupSync();

    // step 4: this thread owns k2 = lane; DFT over n1
    [unroll] for (uint n1 = 0; n1 < N1; ++n1) r[n1] = xchg[off + lane * N1 + n1];
    dft16(r);
    // output X[k1*N2 + k2]
    [unroll] for (uint k1 = 0; k1 < N1; ++k1) xchg[off + k1 * N2 + lane] = r[k1];
    GroupMemoryBarrierWithGroupSync();
}

[shader("compute")][numthreads(256,1,1)]
void coarseReg(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
               StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
               RWStructuredBuffer<float> peakMag,
               uniform uint ntmpl, uniform uint nfull, uniform uint npairs)
{
    uint slot = lid.x / TPT, lane = lid.x % TPT;
    uint pair = gid.x * SLOTS + slot;
    uint off = slot * LEN;
    if (pair < npairs) {
        uint d = pair / ntmpl, t = pair % ntmpl;
        [unroll] for (uint i = 0; i < LEN / TPT; ++i) {
            uint idx = lane + TPT * i;
            xchg[off + idx] = cmulConj(data[d * nfull + idx], tmpl[t * nfull + idx]);
        }
    }
    GroupMemoryBarrierWithGroupSync();

    ifftReg(off, lane);

    float best = -1.0f;
    for (uint i = lane; i < LEN; i += TPT) {
        float2 c = xchg[off + i];
        best = max(best, c.x*c.x + c.y*c.y);
    }
    // reduce across the TPT lanes of this slot
    for (uint st = TPT / 2; st > 0; st >>= 1) {
        float o = WaveShuffle(best, WaveGetLaneIndex() + st);
        if (lane < st) best = max(best, o);
    }
    if (lane == 0 && pair < npairs) peakMag[pair] = sqrt(best);
}
