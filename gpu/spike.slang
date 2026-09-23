// Phase-1 spike: is fusing the correlation and the peak scan worth a
// bespoke kernel?
//
// Three entry points, so the question can be measured rather than argued:
//   fused    -- multiply, inverse transform, peak scan, one dispatch,
//               writes ONE record per pair
//   corr     -- multiply and inverse transform, writes n complex samples
//   reduce   -- second pass over those samples to find the peak
//
// fused against (corr + reduce) is the honest comparison: the second pair
// is what calling a vendor FFT and reducing afterwards costs.

static const uint N = 2048;          // spike length
static const uint WG = 256;          // threads per workgroup
static const uint PER = N / WG;      // points per thread

// Stockham autosort, radix 2, double-buffered in threadgroup memory.
// 2 * 1024 * 8 B = 16 KB, comfortably inside the 64 KB an RDNA workgroup
// gets. No bit-reversal pass and no in-register shuffles: every stage is a
// contiguous read and a contiguous write, which is the same property that
// makes the CPU's balanced split cheap.
groupshared float2 bufA[N];
groupshared float2 bufB[N];
groupshared float  pk[WG];
groupshared uint   pkIdx[WG];


float2 cmul(float2 a, float2 b) { return float2(a.x*b.x - a.y*b.y, a.x*b.y + a.y*b.x); }
float2 cmulConj(float2 a, float2 b) { return float2(a.x*b.x + a.y*b.y, a.y*b.x - a.x*b.y); }

// One inverse transform of bufA, leaving the result in bufA.
//
// RADIX 4. N = 4^5 at N=1024, so five stages instead of radix-2's ten --
// half the barriers and half the trips through threadgroup memory, for a
// butterfly that does a little over twice the arithmetic. Measured at
// 0.044 ms for radix 2; see the comment at the bottom of this file.
void ifftShared(uint tid)
{
    uint quarter = N / 4;
    uint half = N / 2;
    bool inA = true;
    uint s0 = 1;

    // N is a power of two but not always a power of FOUR -- the library
    // supports 1024, 2048, 4096, 8192 and up, so the odd powers need one
    // radix-2 stage to make the rest divisible by four. Doing it first
    // keeps every later stage a clean radix-4.
    bool oddPower = (firstbithigh(N) & 1) == 1;
    if (oddPower) {
        for (uint j = tid; j < half; j += WG) {
            float2 u = bufA[j], v = bufA[j + half];
            bufB[2 * j] = u + v; bufB[2 * j + 1] = u - v;
        }
        GroupMemoryBarrierWithGroupSync();
        inA = false;
        s0 = 2;
    }

    for (uint s = s0; s < N; s <<= 2) {
        for (uint j = tid; j < quarter; j += WG) {
            uint k = j & (s - 1);
            uint base = (j - k) << 2;
            float ang = 2.0f * 3.14159265358979f * float(k) / float(4 * s);
            float2 w1 = float2(cos(ang), sin(ang));          // + : inverse
            float2 w2 = cmul(w1, w1);
            float2 w3 = cmul(w2, w1);

            float2 x0, x1, x2, x3;
            if (inA) {
                x0 = bufA[j]; x1 = bufA[j + quarter];
                x2 = bufA[j + 2 * quarter]; x3 = bufA[j + 3 * quarter];
            } else {
                x0 = bufB[j]; x1 = bufB[j + quarter];
                x2 = bufB[j + 2 * quarter]; x3 = bufB[j + 3 * quarter];
            }
            float2 a = x0, b = cmul(w1, x1), c = cmul(w2, x2), d = cmul(w3, x3);
            float2 t0 = a + c, t1 = a - c, t2 = b + d, t3 = b - d;
            float2 jt3 = float2(-t3.y, t3.x);                // multiply by +i
            float2 o0 = t0 + t2, o1 = t1 + jt3, o2 = t0 - t2, o3 = t1 - jt3;
            if (inA) {
                bufB[base + k] = o0;         bufB[base + k + s] = o1;
                bufB[base + k + 2 * s] = o2; bufB[base + k + 3 * s] = o3;
            } else {
                bufA[base + k] = o0;         bufA[base + k + s] = o1;
                bufA[base + k + 2 * s] = o2; bufA[base + k + 3 * s] = o3;
            }
        }
        GroupMemoryBarrierWithGroupSync();
        inA = !inA;
    }
    if (!inA) {
        for (uint i = tid; i < N; i += WG) bufA[i] = bufB[i];
        GroupMemoryBarrierWithGroupSync();
    }
}

void loadProduct(uint tid, uint d, uint t,
                 StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl)
{
    for (uint i = tid; i < N; i += WG)
        bufA[i] = cmulConj(data[d * N + i], tmpl[t * N + i]);
    GroupMemoryBarrierWithGroupSync();
}

// peak over bufA, written by lane 0
void peakShared(uint tid, uint pair,
                RWStructuredBuffer<float> peakMag,
                RWStructuredBuffer<uint> peakIdx)
{
    float best = -1.0f; uint bi = 0;
    for (uint i = tid; i < N; i += WG) {
        float m = bufA[i].x * bufA[i].x + bufA[i].y * bufA[i].y;
        if (m > best) { best = m; bi = i; }
    }
    pk[tid] = best; pkIdx[tid] = bi;
    GroupMemoryBarrierWithGroupSync();
    for (uint s = WG / 2; s > 0; s >>= 1) {
        if (tid < s && pk[tid + s] > pk[tid]) { pk[tid] = pk[tid + s]; pkIdx[tid] = pkIdx[tid + s]; }
        GroupMemoryBarrierWithGroupSync();
    }
    if (tid == 0) { peakMag[pair] = sqrt(pk[0]); peakIdx[pair] = pkIdx[0]; }
}

[shader("compute")][numthreads(256, 1, 1)]
void fused(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
           StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
           RWStructuredBuffer<float> peakMag, RWStructuredBuffer<uint> peakIdx,
           uniform uint ntmpl)
{
    uint pair = gid.x, tid = lid.x;
    loadProduct(tid, pair / ntmpl, pair % ntmpl, data, tmpl);
    ifftShared(tid);
    peakShared(tid, pair, peakMag, peakIdx);
}

[shader("compute")][numthreads(256, 1, 1)]
void corr(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
          StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
          RWStructuredBuffer<float2> corrOut, uniform uint ntmpl)
{
    uint pair = gid.x, tid = lid.x;
    loadProduct(tid, pair / ntmpl, pair % ntmpl, data, tmpl);
    ifftShared(tid);
    for (uint i = tid; i < N; i += WG) corrOut[pair * N + i] = bufA[i];
}

[shader("compute")][numthreads(256, 1, 1)]
void reduce(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
            StructuredBuffer<float2> corrIn,
            RWStructuredBuffer<float> peakMag, RWStructuredBuffer<uint> peakIdx)
{
    uint pair = gid.x, tid = lid.x;
    float best = -1.0f; uint bi = 0;
    for (uint i = tid; i < N; i += WG) {
        float2 c = corrIn[pair * N + i];
        float m = c.x * c.x + c.y * c.y;
        if (m > best) { best = m; bi = i; }
    }
    pk[tid] = best; pkIdx[tid] = bi;
    GroupMemoryBarrierWithGroupSync();
    for (uint s = WG / 2; s > 0; s >>= 1) {
        if (tid < s && pk[tid + s] > pk[tid]) { pk[tid] = pk[tid + s]; pkIdx[tid] = pkIdx[tid + s]; }
        GroupMemoryBarrierWithGroupSync();
    }
    if (tid == 0) { peakMag[pair] = sqrt(pk[0]); peakIdx[pair] = pkIdx[0]; }
}
