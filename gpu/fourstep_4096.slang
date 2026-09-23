// n=4096 with the threadgroup memory cut 4x, to buy occupancy.
//
// The previous kernel held the whole transform in threadgroup memory: 4096
// complex = 32 KB, which fits two workgroups in a CU's 64 KB, which is 512
// of about 2048 thread slots. By elimination that 25% occupancy is what
// binds it -- not FMA (10% of peak), not LDS bandwidth (8%), not fetching
// (collapsing the working set buys 1.18x).
//
// But the data does not LIVE in threadgroup memory. Each thread holds its
// 16 points in registers; shared memory is only ever a transpose buffer.
// So stage the transposes in chunks: four k2 values at a time, 1024 complex
// = 8 KB, used by both rounds. Occupancy goes 25% -> 100% at the cost of
// more barriers, which is the right trade if latency is the wall.

static const uint WG = 256;
static const uint NBIG = 4096;
static const uint R = 16;            // register radix
static const uint NSUB = 256;        // sub-transform length
static const uint CH = 4;            // k2 values staged per chunk

groupshared float2 stg[CH * NSUB];   // 8 KB
groupshared float  red[WG];

float2 cmul(float2 a, float2 b) { return float2(a.x*b.x - a.y*b.y, a.x*b.y + a.y*b.x); }
float2 cmulConj(float2 a, float2 b) { return float2(a.x*b.x + a.y*b.y, a.y*b.x - a.x*b.y); }

void r4(inout float2 a, inout float2 b, inout float2 c, inout float2 d)
{
    float2 t0 = a + c, t1 = a - c, t2 = b + d, t3 = b - d;
    float2 jt3 = float2(-t3.y, t3.x);
    a = t0 + t2; b = t1 + jt3; c = t0 - t2; d = t1 - jt3;
}

void dft16(inout float2 a[16])
{
    const float2 W1 = float2( 0.92387953f,  0.38268343f);
    const float2 W2 = float2( 0.70710678f,  0.70710678f);
    const float2 W3 = float2( 0.38268343f,  0.92387953f);
    const float2 W4 = float2( 0.0f,         1.0f       );
    const float2 W6 = float2(-0.70710678f,  0.70710678f);
    const float2 W9 = float2(-0.92387953f, -0.38268343f);
    [unroll] for (uint n1 = 0; n1 < 4; ++n1)
        r4(a[n1], a[n1+4], a[n1+8], a[n1+12]);
    a[5]  = cmul(a[5],  W1); a[9]  = cmul(a[9],  W2); a[13] = cmul(a[13], W3);
    a[6]  = cmul(a[6],  W2); a[10] = cmul(a[10], W4); a[14] = cmul(a[14], W6);
    a[7]  = cmul(a[7],  W3); a[11] = cmul(a[11], W6); a[15] = cmul(a[15], W9);
    [unroll] for (uint k2 = 0; k2 < 4; ++k2)
        r4(a[4*k2], a[4*k2+1], a[4*k2+2], a[4*k2+3]);
    float2 t;
    t=a[1];  a[1]=a[4];   a[4]=t;
    t=a[2];  a[2]=a[8];   a[8]=t;
    t=a[3];  a[3]=a[12];  a[12]=t;
    t=a[6];  a[6]=a[9];   a[9]=t;
    t=a[7];  a[7]=a[13];  a[13]=t;
    t=a[11]; a[11]=a[14]; a[14]=t;
}


// 16x16 transpose across the 16 lanes of one slot, in wave shuffles.
//
// No threadgroup memory and no barrier. This is the only way off the
// occupancy cliff for the coarse pass: a 256-point transform needs a
// 256-complex transpose buffer per 16 threads, which is 128 bytes per
// thread however the workgroup is shaped, where full occupancy allows 32.
// Batching more or fewer transforms per workgroup cannot change that
// ratio -- only not using the memory can.
//
// Four butterfly steps. At step s a lane exchanges with lane^s, and the
// REGISTER index swaps with it: out[lane][i] takes cur[lane^s][i^s]
// exactly when (lane & s) and (i & s) differ. Every index is static, so
// the registers stay registers. Verified against a reference transpose
// before being written here.
//
// A slot is 16 lanes and never straddles a wave, on wave32 or wave64.
void transpose16(inout float2 v[16], uint lane)
{
    uint base = WaveGetLaneIndex() - lane;     // this slot's first wave lane
    [unroll] for (uint s = 1; s < 16; s <<= 1) {
        float2 recv[16];
        [unroll] for (uint i = 0; i < 16; ++i)
            recv[i] = WaveShuffle(v[i ^ s], base + (lane ^ s));
        [unroll] for (uint i = 0; i < 16; ++i)
            if (((lane & s) != 0) != ((i & s) != 0)) v[i] = recv[i];
    }
}

// Round 1 -> round 2 exchange, chunked.
//
// Thread tid holds A[n1=tid][k2] for k2 = 0..15. Thread tid needs, for its
// block b = tid/16 and lane = tid%16, the values A[lane + 16*n2][b] for
// n2 = 0..15. Staging four k2 at a time costs 4*256 complex = 8 KB rather
// than the 32 KB the whole transform would take.
void exchangeOuter(inout float2 r[16], uint tid)
{
    uint b = tid / R, lane = tid % R;
    float2 out[16];
    [unroll] for (uint c = 0; c < R / CH; ++c) {
        GroupMemoryBarrierWithGroupSync();
        [unroll] for (uint j = 0; j < CH; ++j) stg[j * NSUB + tid] = r[c * CH + j];
        GroupMemoryBarrierWithGroupSync();
        if (b >= c * CH && b < (c + 1) * CH) {
            uint s = (b - c * CH) * NSUB;
            [unroll] for (uint n2 = 0; n2 < R; ++n2) out[n2] = stg[s + lane + R * n2];
        }
    }
    [unroll] for (uint i = 0; i < R; ++i) r[i] = out[i];
}

// The same, one level down: inside a 256-point sub-transform done by the
// 16 threads of one block. Each block stages CH*16 = 64 complex, and the
// 16 blocks together fill the same 8 KB buffer.
void exchangeInner(inout float2 r[16], uint b, uint lane)
{
    float2 out[16];
    [unroll] for (uint c = 0; c < R / CH; ++c) {
        GroupMemoryBarrierWithGroupSync();
        [unroll] for (uint j = 0; j < CH; ++j) stg[b * CH * R + j * R + lane] = r[c * CH + j];
        GroupMemoryBarrierWithGroupSync();
        if (lane >= c * CH && lane < (c + 1) * CH) {
            uint s = b * CH * R + (lane - c * CH) * R;
            [unroll] for (uint n1 = 0; n1 < R; ++n1) out[n1] = stg[s + n1];
        }
    }
    [unroll] for (uint i = 0; i < R; ++i) r[i] = out[i];
}

[shader("compute")][numthreads(256,1,1)]
void fusedOcc(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
              StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
              RWStructuredBuffer<float> peakMag, uniform uint ntmpl)
{
    uint pair = gid.x, tid = lid.x;
    uint d = pair / ntmpl, t = pair % ntmpl;
    uint b = tid / R, lane = tid % R;
    float2 r[16];

    // gather this thread's column straight from global: n = n1 + NSUB*n2
    [unroll] for (uint n2 = 0; n2 < R; ++n2) {
        uint idx = tid + NSUB * n2;
        r[n2] = cmulConj(data[d * NBIG + idx], tmpl[t * NBIG + idx]);
    }
    dft16(r);
    [unroll] for (uint k2 = 0; k2 < R; ++k2) {
        float ang = 2.0f * 3.14159265358979f * float(tid * k2) / float(NBIG);
        r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
    }
    exchangeOuter(r, tid);

    // now this thread holds 16 points of block b's 256-point transform,
    // as its length-16 column; finish that as a 16x16 four-step
    dft16(r);
    [unroll] for (uint k2 = 0; k2 < R; ++k2) {
        float ang = 2.0f * 3.14159265358979f * float(lane * k2) / float(NSUB);
        r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
    }
    exchangeInner(r, b, lane);
    dft16(r);

    float best = -1.0f;
    [unroll] for (uint i = 0; i < R; ++i) best = max(best, r[i].x*r[i].x + r[i].y*r[i].y);
    uint lanes = WaveGetLaneCount();
    best = WaveActiveMax(best);
    if (WaveGetLaneIndex() == 0) red[tid / lanes] = best;
    GroupMemoryBarrierWithGroupSync();
    if (tid == 0) {
        uint nw = (WG + lanes - 1) / lanes;
        float m = red[0];
        for (uint w = 1; w < nw; ++w) m = max(m, red[w]);
        peakMag[pair] = sqrt(m);
    }
}


[shader("compute")][numthreads(256,1,1)]
void refineOcc(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
               StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
               RWStructuredBuffer<float> peakMag,
               StructuredBuffer<uint> worklist, StructuredBuffer<uint> counter,
               uniform uint ntmpl)
{
    if (gid.x >= counter[0]) return;
    uint pair = worklist[gid.x], tid = lid.x;
    uint d = pair / ntmpl, t = pair % ntmpl;
    uint b = tid / R, lane = tid % R;
    float2 r[16];
    [unroll] for (uint n2 = 0; n2 < R; ++n2) {
        uint idx = tid + NSUB * n2;
        r[n2] = cmulConj(data[d * NBIG + idx], tmpl[t * NBIG + idx]);
    }
    dft16(r);
    [unroll] for (uint k2 = 0; k2 < R; ++k2) {
        float ang = 2.0f * 3.14159265358979f * float(tid * k2) / float(NBIG);
        r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
    }
    exchangeOuter(r, tid);
    dft16(r);
    [unroll] for (uint k2 = 0; k2 < R; ++k2) {
        float ang = 2.0f * 3.14159265358979f * float(lane * k2) / float(NSUB);
        r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
    }
    exchangeInner(r, b, lane);
    dft16(r);
    float best = -1.0f;
    [unroll] for (uint i = 0; i < R; ++i) best = max(best, r[i].x*r[i].x + r[i].y*r[i].y);
    uint lanes = WaveGetLaneCount();
    best = WaveActiveMax(best);
    if (WaveGetLaneIndex() == 0) red[tid / lanes] = best;
    GroupMemoryBarrierWithGroupSync();
    if (tid == 0) {
        uint nw = (WG + lanes - 1) / lanes;
        float m = red[0];
        for (uint w = 1; w < nw; ++w) m = max(m, red[w]);
        peakMag[pair] = sqrt(m);
    }
}


// Coarse pass with the same treatment. The register four-step version held
// 16 slots x 256 complex = 32 KB and was therefore back at 25% occupancy --
// once the full-length kernel was fixed it became the bottleneck, running
// 8x its own ideal. Each slot's 16x16 exchange is staged in chunks, so the
// sixteen slots share the same 8 KB buffer.
[shader("compute")][numthreads(256,1,1)]
void coarseOcc(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
               StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
               RWStructuredBuffer<float> peakMag,
               RWStructuredBuffer<uint> worklist, RWStructuredBuffer<uint> counter,
               uniform uint ntmpl, uniform uint nfull, uniform uint npairs,
               uniform float tcoarse)
{
    uint tid = lid.x, slot = tid / R, lane = tid % R;
    uint pair = gid.x * R + slot;             // R slots per workgroup
    float2 r[16];
    if (pair < npairs) {
        uint d = pair / ntmpl, t = pair % ntmpl;
        // this slot owns a 256-point transform; thread `lane` owns column
        // n1 = lane, gathering with stride R
        [unroll] for (uint n2 = 0; n2 < R; ++n2) {
            uint idx = lane + R * n2;
            r[n2] = cmulConj(data[d * nfull + idx], tmpl[t * nfull + idx]);
        }
    } else {
        [unroll] for (uint i = 0; i < R; ++i) r[i] = float2(0.0f, 0.0f);
    }
    dft16(r);
    [unroll] for (uint k2 = 0; k2 < R; ++k2) {
        float ang = 2.0f * 3.14159265358979f * float(lane * k2) / float(NSUB);
        r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
    }
    exchangeInner(r, slot, lane);
    dft16(r);

    float best = -1.0f;
    [unroll] for (uint i = 0; i < R; ++i) best = max(best, r[i].x*r[i].x + r[i].y*r[i].y);
    // reduce the R lanes of this slot; R <= wave width and a slot never
    // straddles a wave boundary, so the partner is always in this slot
    [unroll] for (uint st = R / 2; st > 0; st >>= 1) {
        float o = WaveShuffle(best, WaveGetLaneIndex() + st);
        if (lane < st) best = max(best, o);
    }
    if (lane == 0 && pair < npairs) {
        if (sqrt(best) > tcoarse) { uint s2; InterlockedAdd(counter[0], 1u, s2); worklist[s2] = pair; }
        else peakMag[pair] = 0.0f;
    }
}


[shader("compute")][numthreads(256,1,1)]
void coarseShuf(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
                StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
                RWStructuredBuffer<float> peakMag,
                RWStructuredBuffer<uint> worklist, RWStructuredBuffer<uint> counter,
                uniform uint ntmpl, uniform uint nfull, uniform uint npairs,
                uniform float tcoarse)
{
    uint tid = lid.x, slot = tid / R, lane = tid % R;
    uint pair = gid.x * R + slot;
    float2 r[16];
    if (pair < npairs) {
        uint d = pair / ntmpl, t = pair % ntmpl;
        [unroll] for (uint n2 = 0; n2 < R; ++n2) {
            uint idx = lane + R * n2;
            r[n2] = cmulConj(data[d * nfull + idx], tmpl[t * nfull + idx]);
        }
    } else {
        [unroll] for (uint i = 0; i < R; ++i) r[i] = float2(0.0f, 0.0f);
    }
    dft16(r);
    [unroll] for (uint k2 = 0; k2 < R; ++k2) {
        float ang = 2.0f * 3.14159265358979f * float(lane * k2) / float(NSUB);
        r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
    }
    transpose16(r, lane);
    dft16(r);

    float best = -1.0f;
    [unroll] for (uint i = 0; i < R; ++i) best = max(best, r[i].x*r[i].x + r[i].y*r[i].y);
    [unroll] for (uint st = R / 2; st > 0; st >>= 1) {
        float o = WaveShuffle(best, WaveGetLaneIndex() + st);
        if (lane < st) best = max(best, o);
    }
    if (lane == 0 && pair < npairs) {
        if (sqrt(best) > tcoarse) { uint s2; InterlockedAdd(counter[0], 1u, s2); worklist[s2] = pair; }
        else peakMag[pair] = 0.0f;
    }
}


// Clearing the worklist counter from the HOST cost 0.0125 ms per call --
// more than the coarse pass's actual GPU work at 2048 pairs. Do it on the
// device instead. A real caller would fold this into the previous
// dispatch; kept separate here so the benchmark can attribute it.
[shader("compute")][numthreads(1,1,1)]
void clearCounter(RWStructuredBuffer<uint> counter) { counter[0] = 0u; }
