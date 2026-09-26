// Hierarchical matched filter, first stage fused across a tile of the batch.
//
// One workgroup owns TILE pairs and does the whole job for them:
//
//   phase 1  all TILE coarse transforms at once, TP threads each, so every
//            lane has a butterfly instead of three quarters idling through
//            the barriers -- which is why the unbatched coarse pass came
//            out slower than the full transform it was meant to avoid.
//   phase 2  walk the survivors IN THIS TILE one at a time, each using all
//            WG threads at full length.
//
// Nothing leaves the workgroup between the phases: no compaction through
// global memory, no second dispatch, and the tile's spectra are already
// resident. Threads stay occupied in both phases, which is the point --
// the coarse pass is wide-and-shallow, the refine pass narrow-and-deep,
// and a single workgroup shape cannot serve both.
//
// TILE and TP are the variants worth sweeping; see sweep.py.

#ifndef TILE
#define TILE 8
#endif
#ifndef NFULL
#define NFULL 1024
#endif
#ifndef NBAND
#define NBAND 256
#endif

static const uint N = NFULL;
static const uint BAND = NBAND;
static const uint WG = 256;
static const uint TP = WG / TILE;          // threads per coarse transform

// Two buffers of TILE*BAND serve phase 1; phase 2 reuses them for one
// full-length transform, which needs 2*N and fits while TILE*BAND >= N.
groupshared float2 bA[TILE * BAND];
groupshared float2 bB[TILE * BAND];
groupshared float  red[WG];
groupshared uint   redI[WG];
groupshared uint   surv[TILE];
groupshared uint   nsurv;

float2 cmul(float2 a, float2 b) { return float2(a.x*b.x - a.y*b.y, a.x*b.y + a.y*b.x); }
float2 cmulConj(float2 a, float2 b) { return float2(a.x*b.x + a.y*b.y, a.y*b.x - a.x*b.y); }

// Stockham radix-4 (+ a leading radix-2 for odd powers of two) over `len`
// points starting at `off`, using `nthread` threads indexed by `lane`.
bool fftSeg(uint off, uint len, uint lane, uint nthread)
{
    uint quarter = len / 4, half = len / 2;
    bool inA = true; uint s0 = 1;
    if ((firstbithigh(len) & 1) == 1) {
        for (uint j = lane; j < half; j += nthread) {
            float2 u = bA[off + j], v = bA[off + j + half];
            bB[off + 2*j] = u + v; bB[off + 2*j + 1] = u - v;
        }
        GroupMemoryBarrierWithGroupSync();
        inA = false; s0 = 2;
    }
    for (uint s = s0; s < len; s <<= 2) {
        for (uint j = lane; j < quarter; j += nthread) {
            uint k = j & (s - 1);
            uint base = (j - k) << 2;
            float ang = 2.0f * 3.14159265358979f * float(k) / float(4 * s);
            float2 w1 = float2(cos(ang), sin(ang));
            float2 w2 = cmul(w1, w1), w3 = cmul(w2, w1);
            float2 x0, x1, x2, x3;
            if (inA) { x0=bA[off+j]; x1=bA[off+j+quarter]; x2=bA[off+j+2*quarter]; x3=bA[off+j+3*quarter]; }
            else     { x0=bB[off+j]; x1=bB[off+j+quarter]; x2=bB[off+j+2*quarter]; x3=bB[off+j+3*quarter]; }
            float2 a=x0, b=cmul(w1,x1), c=cmul(w2,x2), e=cmul(w3,x3);
            float2 t0=a+c, t1=a-c, t2=b+e, t3=b-e;
            float2 jt3 = float2(-t3.y, t3.x);
            float2 o0=t0+t2, o1=t1+jt3, o2=t0-t2, o3=t1-jt3;
            if (inA) { bB[off+base+k]=o0; bB[off+base+k+s]=o1; bB[off+base+k+2*s]=o2; bB[off+base+k+3*s]=o3; }
            else     { bA[off+base+k]=o0; bA[off+base+k+s]=o1; bA[off+base+k+2*s]=o2; bA[off+base+k+3*s]=o3; }
        }
        GroupMemoryBarrierWithGroupSync();
        inA = !inA;
    }
    return inA;
}

[shader("compute")][numthreads(256,1,1)]
void fusedHier(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
               StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
               RWStructuredBuffer<float> peakMag, RWStructuredBuffer<uint> peakIdx,
               RWStructuredBuffer<uint> escalated,
               uniform uint ntmpl, uniform float tcoarse, uniform uint npairs)
{
    uint tid = lid.x;
    uint slot = tid / TP, lane = tid % TP;
    uint pair0 = gid.x * TILE;
    uint pair = pair0 + slot;
    uint off = slot * BAND;

    if (tid == 0) nsurv = 0;
    GroupMemoryBarrierWithGroupSync();

    // ---- phase 1: every coarse transform in the tile, all lanes busy ----
    if (pair < npairs) {
        uint d = pair / ntmpl, t = pair % ntmpl;
        for (uint i = lane; i < BAND; i += TP)
            bA[off + i] = cmulConj(data[d * N + i], tmpl[t * N + i]);
    }
    GroupMemoryBarrierWithGroupSync();

    bool inA = fftSeg(off, BAND, lane, TP);

    float best = -1.0f;
    for (uint i = lane; i < BAND; i += TP) {
        float2 c = inA ? bA[off + i] : bB[off + i];
        best = max(best, c.x*c.x + c.y*c.y);
    }
    red[tid] = best;
    GroupMemoryBarrierWithGroupSync();
    for (uint st = TP / 2; st > 0; st >>= 1) {
        if (lane < st && red[tid + st] > red[tid]) red[tid] = red[tid + st];
        GroupMemoryBarrierWithGroupSync();
    }
    if (lane == 0 && pair < npairs) {
        if (sqrt(red[tid]) > tcoarse) {
            uint s2; InterlockedAdd(nsurv, 1u, s2); surv[s2] = pair;
        } else {
            peakMag[pair] = 0.0f; peakIdx[pair] = 0xffffffffu;
        }
    }
    GroupMemoryBarrierWithGroupSync();

    uint ns = nsurv;
    if (tid == 0) InterlockedAdd(escalated[0], ns);

    // ---- phase 2: the survivors, one at a time, all WG threads on each ----
    for (uint si = 0; si < ns; ++si) {
        uint p = surv[si];
        uint d = p / ntmpl, t = p % ntmpl;
        GroupMemoryBarrierWithGroupSync();
        for (uint i = tid; i < N; i += WG)
            bA[i] = cmulConj(data[d * N + i], tmpl[t * N + i]);
        GroupMemoryBarrierWithGroupSync();
        bool fa = fftSeg(0, N, tid, WG);
        float b2 = -1.0f; uint bi = 0;
        for (uint i = tid; i < N; i += WG) {
            float2 c = fa ? bA[i] : bB[i];
            float m = c.x*c.x + c.y*c.y;
            if (m > b2) { b2 = m; bi = i; }
        }
        red[tid] = b2; redI[tid] = bi;
        GroupMemoryBarrierWithGroupSync();
        for (uint st = WG / 2; st > 0; st >>= 1) {
            if (tid < st && red[tid + st] > red[tid]) { red[tid] = red[tid + st]; redI[tid] = redI[tid + st]; }
            GroupMemoryBarrierWithGroupSync();
        }
        if (tid == 0) { peakMag[p] = sqrt(red[0]); peakIdx[p] = redI[0]; }
    }
}
