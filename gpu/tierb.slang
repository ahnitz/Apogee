// Tier B: every transform length one workgroup can carry.
//
// L = TB*16 with TB threads holding 16 points each: a 16-point DFT per
// thread over its stride-TB column, a twiddle, a transpose among those TB
// threads, then TB-point transforms per block carried by TB/16 threads --
// recursing until TB <= 16, where a thread's 16 registers hold 16/TB whole
// blocks and it finishes them with no exchange at all.
//
// Verified in gpu/decomposition.py before any of this was written, for
// 1024 through 16384. n >= 32768 wants more than 1024 threads and is
// Tier C.
//
//   n      threads  recursion     innermost
//   1024      64    64->4         4 blocks of 4 per thread
//   2048     128    128->8        2 blocks of 8
//   4096     256    256->16       1 block of 16
//   8192     512    512->32->2    8 blocks of 2
//  16384    1024    1024->64->4   4 blocks of 4

#ifndef NLEN
#define NLEN 1024
#endif
static const uint N   = NLEN;
static const uint R   = 16;
static const uint WG  = NLEN / 16;        // threads per transform
static const float PI = 3.14159265358979f;

//: The exchange is staged in chunks so the threadgroup array is a fixed
//: 8 KB at every length, rather than sized to the transform -- which was
//: 128 KB at n=16384, over every device's limit, and already past Apple's
//: 32 KB at n=4096. CH registers of every thread are in flight at once.
static const uint CAP = 1024;                  // complex, = 8 KB
static const uint CH  = (CAP / WG > 0) ? (CAP / WG) : 1;
groupshared float2 stg[CH * WG];
static uint _tid;

float2 cmul(float2 a, float2 b) { return float2(a.x*b.x - a.y*b.y, a.x*b.y + a.y*b.x); }
float2 cmulConj(float2 a, float2 b) { return float2(a.x*b.x + a.y*b.y, a.y*b.x - a.x*b.y); }

void r4(inout float2 a, inout float2 b, inout float2 c, inout float2 d)
{
    float2 t0=a+c, t1=a-c, t2=b+d, t3=b-d;
    float2 j3 = float2(-t3.y, t3.x);
    a=t0+t2; b=t1+j3; c=t0-t2; d=t1-j3;
}

// In-register DFTs at COMPILE-TIME sizes and offsets. A runtime offset
// or length here indexes the register array dynamically, which forces a
// spill to scratch -- the first version did that and the driver crashed.
// The innermost block size follows from NLEN, so it folds.
void dft2(inout float2 r[16], uint o)
{
    float2 a=r[o], b=r[o+1]; r[o]=a+b; r[o+1]=a-b;
}
void dft4(inout float2 r[16], uint o)
{
    r4(r[o], r[o+1], r[o+2], r[o+3]);
    float2 t=r[o+1]; r[o+1]=r[o+2]; r[o+2]=t;
}
void dft8(inout float2 r[16], uint o)
{
    // radix-2, three stages, fully unrolled with static indices
    const float S = 0.70710678f;
    float2 b[8];
    [unroll] for (uint s = 1; s < 8; s <<= 1) {
        [unroll] for (uint j = 0; j < 4; ++j) {
            uint k = j & (s-1), base = (j-k) << 1;
            float ang = PI * float(k) / float(s);
            float2 w = float2(cos(ang), sin(ang));
            float2 u = r[o+j], v = r[o+j+4], t = cmul(w, v);
            b[base+k] = u+t; b[base+k+s] = u-t;
        }
        [unroll] for (uint i = 0; i < 8; ++i) r[o+i] = b[i];
    }
}
void dft16(inout float2 r[16])
{
    const float2 W1 = float2( 0.92387953f,  0.38268343f);
    const float2 W2 = float2( 0.70710678f,  0.70710678f);
    const float2 W3 = float2( 0.38268343f,  0.92387953f);
    const float2 W4 = float2( 0.0f,         1.0f       );
    const float2 W6 = float2(-0.70710678f,  0.70710678f);
    const float2 W9 = float2(-0.92387953f, -0.38268343f);
    [unroll] for (uint n1 = 0; n1 < 4; ++n1) r4(r[n1], r[n1+4], r[n1+8], r[n1+12]);
    r[5]=cmul(r[5],W1);  r[9]=cmul(r[9],W2);   r[13]=cmul(r[13],W3);
    r[6]=cmul(r[6],W2);  r[10]=cmul(r[10],W4); r[14]=cmul(r[14],W6);
    r[7]=cmul(r[7],W3);  r[11]=cmul(r[11],W6); r[15]=cmul(r[15],W9);
    [unroll] for (uint k2 = 0; k2 < 4; ++k2) r4(r[4*k2], r[4*k2+1], r[4*k2+2], r[4*k2+3]);
    float2 t;
    t=r[1];  r[1]=r[4];   r[4]=t;
    t=r[2];  r[2]=r[8];   r[8]=t;
    t=r[3];  r[3]=r[12];  r[12]=t;
    t=r[6];  r[6]=r[9];   r[9]=t;
    t=r[7];  r[7]=r[13];  r[13]=t;
    t=r[11]; r[11]=r[14]; r[14]=t;
}

//: Innermost block size: recurse TB /= 16 until it fits in a thread.
static const uint INNER = (WG <= 16) ? WG : ((WG / 16 <= 16) ? WG / 16 : WG / 256);

void innermost(inout float2 r[16])
{
    if (INNER == 16)     { dft16(r); }
    else if (INNER == 8) { [unroll] for (uint b = 0; b < 2; ++b) dft8(r, b*8); }
    else if (INNER == 4) { [unroll] for (uint b = 0; b < 4; ++b) dft4(r, b*4); }
    else                 { [unroll] for (uint b = 0; b < 8; ++b) dft2(r, b*2); }
}

// Exchange in chunks. Staging CH registers of every thread at a time,
// a reader works out for each value it wants which register of which
// thread wrote it -- the scatter formula inverts -- and takes it when
// that register falls in the current chunk.
//
//   scatter wrote   p = blk*len + i*span + lane
//   so from p:      blk = p/len, i = (p%len)/span, lane = (p%len)%span
//                   writer thread = blk*span + lane
void exchange(inout float2 r[16], uint want[16], uint lgLen, uint lgSpan)
{
    // Every divisor here is a power of two, so these are shifts and masks.
    // Written as / and % they were integer divisions -- 16 of them per
    // thread per chunk -- and cost n=4096 a third of its throughput
    // against the hand-specialised kernel.
    float2 out[16];
    uint spanMask = (1u << lgSpan) - 1u;
    uint lenMask  = (1u << lgLen) - 1u;
    [unroll] for (uint c = 0; c < R / CH; ++c) {
        GroupMemoryBarrierWithGroupSync();
        [unroll] for (uint j = 0; j < CH; ++j) stg[j * WG + _tid] = r[c * CH + j];
        GroupMemoryBarrierWithGroupSync();
        [unroll] for (uint d = 0; d < R; ++d) {
            uint p = want[d];
            uint b = p >> lgLen, rem = p & lenMask;
            uint i = rem >> lgSpan, ln = rem & spanMask;
            if (i >= c * CH && i < (c + 1) * CH)
                out[d] = stg[(i - c * CH) * WG + (b << lgSpan) + ln];
        }
    }
    [unroll] for (uint d = 0; d < R; ++d) r[d] = out[d];
}

[shader("compute")][numthreads(WG,1,1)]
void fusedTierB(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
                StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
                RWStructuredBuffer<float> peakMag, uniform uint ntmpl)
{
    uint pair = gid.x, tid = lid.x;
    _tid = tid;
    uint d = pair / ntmpl, t = pair % ntmpl;
    float2 r[16];

    // level 0: gather this thread's stride-WG column straight from global
    [unroll] for (uint n2 = 0; n2 < R; ++n2) {
        uint idx = tid + WG * n2;
        r[n2] = cmulConj(data[d*N + idx], tmpl[t*N + idx]);
    }

    uint TB = WG, len = N, blk = 0, lane = tid;
    uint lgLen = firstbithigh(N), lgTB = firstbithigh(WG);
    uint want[16];
    while (true) {
        dft16(r);
        [unroll] for (uint k2 = 0; k2 < R; ++k2) {
            float ang = 2.0f * PI * float(lane * k2) / float(len);
            r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
        }
        if (TB <= R) {
            uint per = R / TB;
            [unroll] for (uint d = 0; d < R; ++d) {
                uint j = d / TB, m = d % TB;
                want[d] = blk * len + (lane * per + j) * TB + m;
            }
            exchange(r, want, lgLen, lgTB);
            break;
        }
        uint len2 = TB, TB2 = TB / R;
        uint blk2 = tid / TB2, lane2 = tid % TB2;
        [unroll] for (uint d = 0; d < R; ++d)
            want[d] = blk2 * len2 + lane2 + TB2 * d;
        exchange(r, want, lgLen, lgTB);
        len = len2; TB = TB2; blk = blk2; lane = lane2;
        lgLen = firstbithigh(len); lgTB = firstbithigh(TB);
    }
    innermost(r);

    float best = -1.0f;
    [unroll] for (uint i = 0; i < R; ++i) best = max(best, r[i].x*r[i].x + r[i].y*r[i].y);
    best = WaveActiveMax(best);
    GroupMemoryBarrierWithGroupSync();
    if (WaveGetLaneIndex() == 0) stg[tid / WaveGetLaneCount()].x = best;
    GroupMemoryBarrierWithGroupSync();
    if (tid == 0) {
        uint nw = (WG + WaveGetLaneCount() - 1) / WaveGetLaneCount();
        float m = stg[0].x;
        for (uint w = 1; w < nw; ++w) m = max(m, stg[w].x);
        peakMag[pair] = sqrt(m);
    }
}
