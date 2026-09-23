// Full-length transform by nesting the four-step, so n=4096 works at all.
//
// A double-buffered Stockham at 4096 points wants 64 KB of threadgroup
// memory -- the entire budget -- and does not launch. The four-step needs
// one buffer, and nests: N = N1*N2 with N1 = 256 and N2 = 16, where the
// length-256 half is itself a 16x16 four-step. So the whole 4096-point
// transform is three rounds of a 16-point DFT held in registers, with two
// transposes through threadgroup memory.
//
// This is the CPU's balanced split, twice.

static const uint WG = 256;
static const uint NBIG = 4096;
static const uint NSUB = 256;        // N1
static const uint R = 16;            // N2, and the register radix

groupshared float2 sh[NBIG];
groupshared float  red[WG];

float2 cmul(float2 a, float2 b) { return float2(a.x*b.x - a.y*b.y, a.x*b.y + a.y*b.x); }
float2 cmulConj(float2 a, float2 b) { return float2(a.x*b.x + a.y*b.y, a.y*b.x - a.x*b.y); }

void dft16(inout float2 a[16])
{
    float2 b[16];
    [unroll] for (uint s = 1; s < 16; s <<= 1) {
        [unroll] for (uint j = 0; j < 8; ++j) {
            uint k = j & (s - 1);
            uint base = (j - k) << 1;
            float ang = 3.14159265358979f * float(k) / float(s);
            float2 w = float2(cos(ang), sin(ang));
            float2 u = a[j], v = a[j + 8];
            float2 t = cmul(w, v);
            b[base + k] = u + t; b[base + k + s] = u - t;
        }
        [unroll] for (uint i = 0; i < 16; ++i) a[i] = b[i];
    }
}

// length-256 inverse transform of sh[off ..], 16 threads, one transpose
void ifft256(uint off, uint lane)
{
    float2 r[16];
    [unroll] for (uint n2 = 0; n2 < 16; ++n2) r[n2] = sh[off + lane + 16 * n2];
    GroupMemoryBarrierWithGroupSync();      // gathered before anyone scatters
    dft16(r);
    // Each twiddle from its own sin/cos, not walked incrementally. The
    // incremental form (one transcendental plus 16 complex multiplies)
    // looked 1.4x faster and was not: identical work on this box has a
    // 2.41x spread and 29% CV, so the difference was noise. Its accuracy
    // cost was real -- 3.4e-07 to 1.6e-06, from accumulating sixteen
    // multiplies. Unproven speed is not worth measured accuracy.
    [unroll] for (uint k2 = 0; k2 < 16; ++k2) {
        float ang = 2.0f * 3.14159265358979f * float(lane * k2) / 256.0f;
        r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
    }
    [unroll] for (uint k2 = 0; k2 < 16; ++k2) sh[off + k2 * 16 + lane] = r[k2];
    GroupMemoryBarrierWithGroupSync();
    [unroll] for (uint n1 = 0; n1 < 16; ++n1) r[n1] = sh[off + lane * 16 + n1];
    GroupMemoryBarrierWithGroupSync();
    dft16(r);
    [unroll] for (uint k1 = 0; k1 < 16; ++k1) sh[off + k1 * 16 + lane] = r[k1];
    GroupMemoryBarrierWithGroupSync();
}

// length-4096 inverse transform of sh[0 ..], all WG threads
void ifft4096(uint tid)
{
    float2 r[16];
    // step 1: N2=16-point DFT over n2, thread owns n1 = tid (stride 256)
    [unroll] for (uint n2 = 0; n2 < R; ++n2) r[n2] = sh[tid + NSUB * n2];
    GroupMemoryBarrierWithGroupSync();
    dft16(r);
    // step 2: twiddle W_N^(n1*k2)
    [unroll] for (uint k2 = 0; k2 < R; ++k2) {
        float ang = 2.0f * 3.14159265358979f * float(tid * k2) / float(NBIG);
        r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
    }
    // step 3: transpose so each k2 block is contiguous
    [unroll] for (uint k2 = 0; k2 < R; ++k2) sh[k2 * NSUB + tid] = r[k2];
    GroupMemoryBarrierWithGroupSync();
    // step 4: length-256 DFT over n1 within each k2 block; 16 threads each
    ifft256((tid / R) * NSUB, tid % R);
    // output X[k1*R + k2] sits at sh[k2*NSUB + k1]; the peak scan does not
    // care about lag ORDER, only the set of magnitudes -- but the index
    // must be untangled, so report it in transform order and map outside.
}

[shader("compute")][numthreads(256,1,1)]
void fusedBig(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
              StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
              RWStructuredBuffer<float> peakMag, RWStructuredBuffer<float2> dump,
              uniform uint ntmpl, uniform uint dumpPair)
{
    uint pair = gid.x, tid = lid.x;
    uint d = pair / ntmpl, t = pair % ntmpl;
    for (uint i = tid; i < NBIG; i += WG)
        sh[i] = cmulConj(data[d * NBIG + i], tmpl[t * NBIG + i]);
    GroupMemoryBarrierWithGroupSync();
    ifft4096(tid);
    if (pair == dumpPair)
        for (uint i = tid; i < NBIG; i += WG) dump[i] = sh[i];
    float best = -1.0f;
    for (uint i = tid; i < NBIG; i += WG) {
        float2 c = sh[i];
        best = max(best, c.x*c.x + c.y*c.y);
    }
    // Tree reduction through a scratch array, NOT a wave-width assumption.
    // The previous version did `if (WaveIsFirstLane()) sh[tid/32] = best`,
    // which silently assumes wave32. RADV can compile compute as wave64,
    // and then only every other slot was written while the rest still held
    // transform output -- so the reported peak came out LARGER than the
    // true one. Wave width is not a portable constant; Metal's SIMD group
    // is 32, AMD's is 32 or 64 by compiler choice.
    // Two-level and wave-width AGNOSTIC: reduce inside each wave with the
    // hardware op, then reduce the handful of wave results. The width comes
    // from WaveGetLaneCount() at runtime rather than being assumed to be 32,
    // which is what made the first version report peaks larger than the
    // truth on a wave64 compile. One barrier instead of log2(WG) = 8.
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
void refineBig(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
               StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
               RWStructuredBuffer<float> peakMag,
               StructuredBuffer<uint> worklist, StructuredBuffer<uint> counter,
               uniform uint ntmpl)
{
    if (gid.x >= counter[0]) return;
    uint pair = worklist[gid.x], tid = lid.x;
    uint d = pair / ntmpl, t = pair % ntmpl;
    for (uint i = tid; i < NBIG; i += WG)
        sh[i] = cmulConj(data[d * NBIG + i], tmpl[t * NBIG + i]);
    GroupMemoryBarrierWithGroupSync();
    ifft4096(tid);
    float best = -1.0f;
    for (uint i = tid; i < NBIG; i += WG) {
        float2 c = sh[i];
        best = max(best, c.x*c.x + c.y*c.y);
    }
    // Two-level and wave-width AGNOSTIC: reduce inside each wave with the
    // hardware op, then reduce the handful of wave results. The width comes
    // from WaveGetLaneCount() at runtime rather than being assumed to be 32,
    // which is what made the first version report peaks larger than the
    // truth on a wave64 compile. One barrier instead of log2(WG) = 8.
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
