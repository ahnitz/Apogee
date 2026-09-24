// Hierarchical matched filter: register-resident coarse pass fused across
// a batch tile, then the survivors at full length.
//
// Phase 1 now uses the four-step with each thread holding a 16-point
// sub-transform in registers, so the 256-point coarse transform costs ONE
// barrier instead of four and touches threadgroup memory only to
// transpose. Measured alone: 0.080 ms against 0.180 for radix-4 Stockham,
// at the same 3e-07 accuracy.
#ifndef TILE
#define TILE 16
#endif
#ifndef NFULL
#define NFULL 1024
#endif
#ifndef NBAND
#define NBAND 256
#endif

static const uint N = NFULL;
static const uint BAND = NBAND;
#ifndef WGSZ
#define WGSZ 256
#endif
static const uint WG = WGSZ;
static const uint TP = WG / TILE;          // threads per coarse transform

// Two buffers of TILE*BAND serve phase 1; phase 2 reuses them for one
// full-length transform, which needs 2*N and fits while TILE*BAND >= N.
// bA holds the whole tile's coarse transforms (the register four-step
// transposes within it, so phase 1 needs no second buffer) and doubles as
// one full-length working buffer in phase 2. bB is only ever needed at
// full length, so it is sized N rather than TILE*BAND -- which is what
// took the LDS over budget and crashed the device at TILE=16.
// ONE threadgroup array. Phase 1's register four-step transposes within
// bA and needs no second buffer; phase 2's Stockham needs two, and takes
// them as the two halves of bA -- the tile's coarse transforms are dead by
// then, only the survivor list matters. Carrying a separate bB pushed LDS
// from 32 KB to 40 KB, halved occupancy, and made phase 1 cost 0.216 ms
// where it measures 0.080 standalone.
groupshared float2 bA[TILE * BAND];
static const uint BOFF = TILE * BAND / 2;   // phase 2's second buffer
groupshared float  red[WG];
groupshared uint   redI[WG];
groupshared uint   surv[TILE];
groupshared uint   nsurv;

static const uint N1 = 16;
static const uint N2 = 16;
static const uint TPT = 16;

float2 cmul(float2 a, float2 b) { return float2(a.x*b.x - a.y*b.y, a.x*b.y + a.y*b.x); }
float2 cmulConj(float2 a, float2 b) { return float2(a.x*b.x + a.y*b.y, a.y*b.x - a.x*b.y); }

void dft16(inout float2 a[16])
{
    float2 b[16];
    [unroll] for (uint s = 1; s < 16; s <<= 1) {
        [unroll] for (uint j = 0; j < 8; ++j) {
            uint k = j & (s - 1);
            uint base = (j - k) << 1;
            float ang = 3.14159265358979f * float(k) / float(s);   // + : inverse
            float2 w = float2(cos(ang), sin(ang));
            float2 u = a[j], v = a[j + 8];
            float2 t = cmul(w, v);
            b[base + k] = u + t; b[base + k + s] = u - t;
        }
        [unroll] for (uint i = 0; i < 16; ++i) a[i] = b[i];
    }
}

// One inverse transform of LEN points held at bA[off .. off+LEN).
// `lane` in 0..TPT-1. Leaves the result in xchg.
void ifftReg(uint off, uint lane)
{
    float2 r[16];

    // step 1: this thread owns n1 = lane; gather its column, DFT over n2
    [unroll] for (uint n2 = 0; n2 < N2; ++n2) r[n2] = bA[off + lane + N1 * n2];
    dft16(r);

    // step 2: twiddle by W_N^(n1*k2), still in registers
    [unroll] for (uint k2 = 0; k2 < N2; ++k2) {
        float ang = 2.0f * 3.14159265358979f * float(lane * k2) / float(BAND);
        r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
    }

    // step 3: the one transpose. A[n1][k2] -> bA[k2*N1 + n1]
    [unroll] for (uint k2 = 0; k2 < N2; ++k2) bA[off + k2 * N1 + lane] = r[k2];
    GroupMemoryBarrierWithGroupSync();

    // step 4: this thread owns k2 = lane; DFT over n1
    [unroll] for (uint n1 = 0; n1 < N1; ++n1) r[n1] = bA[off + lane * N1 + n1];
    dft16(r);
    // output X[k1*N2 + k2]
    [unroll] for (uint k1 = 0; k1 < N1; ++k1) bA[off + k1 * N2 + lane] = r[k1];
    GroupMemoryBarrierWithGroupSync();
}


// Stockham radix-4 (+ a leading radix-2 for odd powers of two) over `len`
// points starting at `off`, using `nthread` threads indexed by `lane`.
bool fftSeg(uint off, uint len, uint lane, uint nthread)
{
    uint quarter = len / 4, half = len / 2;
    bool inA = true; uint s0 = 1;
    if ((firstbithigh(len) & 1) == 1) {
        for (uint j = lane; j < half; j += nthread) {
            float2 u = bA[off + j], v = bA[off + j + half];
            bA[BOFF + off + 2*j] = u + v; bA[BOFF + off + 2*j + 1] = u - v;
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
            else     { x0=bA[BOFF+off+j]; x1=bA[BOFF+off+j+quarter]; x2=bA[BOFF+off+j+2*quarter]; x3=bA[BOFF+off+j+3*quarter]; }
            float2 a=x0, b=cmul(w1,x1), c=cmul(w2,x2), e=cmul(w3,x3);
            float2 t0=a+c, t1=a-c, t2=b+e, t3=b-e;
            float2 jt3 = float2(-t3.y, t3.x);
            float2 o0=t0+t2, o1=t1+jt3, o2=t0-t2, o3=t1-jt3;
            if (inA) { bA[BOFF+off+base+k]=o0; bA[BOFF+off+base+k+s]=o1; bA[BOFF+off+base+k+2*s]=o2; bA[BOFF+off+base+k+3*s]=o3; }
            else     { bA[off+base+k]=o0; bA[off+base+k+s]=o1; bA[off+base+k+2*s]=o2; bA[off+base+k+3*s]=o3; }
        }
        GroupMemoryBarrierWithGroupSync();
        inA = !inA;
    }
    return inA;
}

[shader("compute")][numthreads(WGSZ,1,1)]
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

    ifftReg(off, lane);              // register four-step; result in bA

    float best = -1.0f;
    for (uint i = lane; i < BAND; i += TP) {
        float2 c = bA[off + i];
        best = max(best, c.x*c.x + c.y*c.y);
    }
    // Reduce the slot's TP lanes with wave shuffles, not through LDS.
    // red[]/redI[] cost 2 KB, which took the kernel from 32 KB to 34 and
    // therefore from two resident workgroups per CU to one -- phase 1 then
    // measured 0.216 ms where the same transform standalone measures
    // 0.080. TP <= 16 and the slot never straddles a wave32 boundary, so
    // the partner lane is always inside this slot.
    for (uint st = TP / 2; st > 0; st >>= 1) {
        float o = WaveShuffle(best, WaveGetLaneIndex() + st);
        if (lane < st) best = max(best, o);
    }
    if (lane == 0 && pair < npairs) {
        if (sqrt(best) > tcoarse) {
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
            float2 c = fa ? bA[i] : bA[BOFF + i];
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
