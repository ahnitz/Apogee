// Tier B: every transform length one workgroup can carry.
//
// L = TB*16 with TB threads holding 16 points each: a 16-point DFT per
// thread over its stride-TB column, a twiddle, a transpose among those TB
// threads, then TB-point transforms per block carried by TB/16 threads --
// recursing until TB <= 16, where a thread's 16 registers hold 16/TB whole
// blocks and it finishes them with no exchange at all.
//
// Verified in tools/gpu_decomposition.py before any of this was written,
// for 1024 through 16384. n >= 32768 wants more than 1024 threads and is
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
//: Staging capacity in complex values. The exchange runs R/CH chunks with
//: CH = CAP/WG, and each chunk costs two barriers -- so a small CAP at a
//: large workgroup is barrier-bound, not bandwidth-bound. Measured at
//: threshold 5.5, 8192 pairs:
//:
//:     n=8192   8 KB 9.6x   16 KB 19.8x   32 KB 23.5x   64 KB 23.8x
//:     n=16384  8 KB 6.6x   16 KB  8.3x   32 KB 14.1x   64 KB 16.2x
//:
//: So it follows the workgroup rather than being fixed. The ceiling is a
//: PORTABILITY limit, not a performance one: 32 KB is what Apple allows a
//: threadgroup, and this device would take 64. MF_LDS_KB overrides it at
//: build time, which is how a per-device variant will be emitted.
#ifndef LDS_CAP
#define LDS_CAP 4096                           // complex, = 32 KB
#endif
static const uint CAP = (R * WG < LDS_CAP) ? (R * WG) : LDS_CAP;
//: Clamped to R. The exchange runs R/CH chunks, so CH > R makes that zero
//: and the exchange never happens -- the kernel then returns a transform of
//: the wrong axis, silently, with plausible magnitudes. That is what it did
//: at every length below 1024, where CAP/WG exceeds 16.
static const uint CH  = ((CAP / WG) > R) ? R : ((CAP / WG > 0) ? (CAP / WG) : 1);
//: Staged as uint so the per-bin peak table can alias this same memory once
//: the transform is finished. A second array would have doubled LDS to 16 KB,
//: and LDS is what caps how many workgroups a CU holds -- the 8 KB here was
//: chosen for occupancy. Measured free: +0.1% against float2 staging.
groupshared uint stg[CH * WG * 2];
void stgPut(uint i, float2 v) { stg[2*i] = asuint(v.x); stg[2*i+1] = asuint(v.y); }
float2 stgGet(uint i) { return float2(asfloat(stg[2*i]), asfloat(stg[2*i+1])); }
static uint _tid;

//: Levels until a block fits in one thread's registers. Known from NLEN,
//: so the level loop unrolls and every len/TB/shift below folds to a
//: constant -- which is the whole difference between this and the
//: hand-specialised kernel.
static const uint NLEVELS = (WG <= 16) ? 1 : ((WG <= 256) ? 2 : 3);

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
    // Explicitly initialised. Every register index falls in exactly one
    // chunk, so these are always written -- but the compiler cannot prove
    // it and warns, and a backend that leaves an unwritten register as
    // garbage rather than zero would turn that warning into a wrong
    // answer. Cheap insurance against a compiler we have not met.
    float2 out[16];
    [unroll] for (uint z = 0; z < R; ++z) out[z] = float2(0.0f, 0.0f);
    uint spanMask = (1u << lgSpan) - 1u;
    uint lenMask  = (1u << lgLen) - 1u;
    [unroll] for (uint c = 0; c < R / CH; ++c) {
        GroupMemoryBarrierWithGroupSync();
        [unroll] for (uint j = 0; j < CH; ++j) stgPut(j * WG + _tid, r[c * CH + j]);
        GroupMemoryBarrierWithGroupSync();
        [unroll] for (uint d = 0; d < R; ++d) {
            uint p = want[d];
            uint b = p >> lgLen, rem = p & lenMask;
            uint i = rem >> lgSpan, ln = rem & spanMask;
            if (i >= c * CH && i < (c + 1) * CH)
                out[d] = stgGet((i - c * CH) * WG + (b << lgSpan) + ln);
        }
    }
    [unroll] for (uint d = 0; d < R; ++d) r[d] = out[d];
}

//: The four-step skips its final transposes, so the transform leaves results
//: in mixed-radix digit-reversed order: register q of thread tid holds output
//: index reverse(tid*16 + q) under radices [16]*NLEVELS + INNER. Established
//: by dumping every register against a float64 reference for all five
//: lengths -- see tools/gpu_output_order.py. INNER=4 contributes [2,2] and not
//: [4]: dft4 leaves its pair bit-reversed, which was measured, not reasoned.
//:
//: A peak MAGNITUDE is order-independent, which is why nothing needed this
//: until the kernel had to report an index and place samples into bins -- and
//: why getting it wrong would be silent rather than loud.
//:
//: Every radix is a power of two, so this is a bit shuffle. The digits come
//: out least-significant first and are consumed in that same order, so
//: extraction and rebuild fuse into one loop with NO array: dynamic indexing
//: of a register array spills to scratch and crashed a driver here once.
static const uint NIDIG = (INNER == 4) ? 2u : 1u;
static const uint NDIG  = NLEVELS + NIDIG;
static const uint LGI0  = (INNER == 2) ? 1u : ((INNER == 4) ? 1u : ((INNER == 8) ? 3u : 4u));

uint lgOf(uint i) { return (i < NLEVELS) ? 4u : ((i == NLEVELS) ? LGI0 : 1u); }

uint slotToIndex(uint slot)
{
    uint idx = 0u, x = slot;
    [ForceUnroll] for (int i = int(NDIG) - 1; i >= 0; --i) {
        uint lg = lgOf(uint(i));
        uint d  = x & ((1u << lg) - 1u);
        x >>= lg;
        idx = (idx << lg) | d;
    }
    return idx;
}

//: The filter itself, as a plain function so more than one entry point can
//: use it. Slang does not allow one entry point to call another, and the
//: gated variant needs exactly this body after its early-out.
void filterPair(uint pair, uint tid,
                StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
                RWStructuredBuffer<int> peakIdx,
                RWStructuredBuffer<float2> peakVal,
                uint ntmpl, uint winStart, uint winEnd,
                uint binsize, int binShift, uint nbins, uint thrBits)
{
    _tid = tid;
    uint d = pair / ntmpl, t = pair % ntmpl;
    float2 r[16];

    // level 0: gather this thread's stride-WG column straight from global
    [unroll] for (uint n2 = 0; n2 < R; ++n2) {
        uint idx = tid + WG * n2;
        r[n2] = cmulConj(data[d*N + idx], tmpl[t*N + idx]);
    }

    [ForceUnroll] for (uint lvl = 0; lvl < NLEVELS; ++lvl) {
        uint want[16];                       // scoped per level
        [unroll] for (uint z = 0; z < R; ++z) want[z] = 0u;
        // lvl is an unrolled constant, so all of these are constants
        const uint TB   = WG >> (4 * lvl);
        const uint len  = N  >> (4 * lvl);
        const uint lgTB = firstbithigh(TB);
        const uint lgLn = firstbithigh(len);
        uint blk  = tid >> lgTB;
        uint lane = tid & (TB - 1);

        dft16(r);
        [unroll] for (uint k2 = 0; k2 < R; ++k2) {
            float ang = 2.0f * PI * float(lane * k2) / float(len);
            r[k2] = cmul(r[k2], float2(cos(ang), sin(ang)));
        }

        // one assignment of want[], then one call: the branchy version
        // left the compiler unsure it was initialised on every path
        const uint per  = R / max(TB, 1u);
        const uint TB2  = max(TB >> 4, 1u), len2 = TB;
        uint blk2 = tid / TB2, lane2 = tid % TB2;
        [unroll] for (uint d = 0; d < R; ++d) {
            uint j = d / max(TB, 1u), m = d % max(TB, 1u);
            want[d] = (TB <= R) ? (blk * len + (lane * per + j) * TB + m)
                                : (blk2 * len2 + lane2 + TB2 * d);
        }
        exchange(r, want, lgLn, lgTB);
    }
    const uint INNER_TB = WG >> (4 * (NLEVELS - 1));
    innermost(r);

    // --- peak per bin ---------------------------------------------------
    // Bins are contiguous in OUTPUT index, and the output index is not
    // contiguous in register or thread space, so every register has to be
    // placed by its true index. A host-side lookup cannot do this.

    // Seeded with the SQUARED THRESHOLD, exactly as the CPU does (bmax[j] =
    // t2). Anything at or below it can never win, so it takes no atomic and
    // no comparison -- and at a real detection threshold almost nothing
    // clears it, often nothing at all in a given bin. Seeding at zero rather
    // than -1 also means a bin whose every |v|^2 underflowed reports index
    // -1 instead of naming the first sample, matching the CPU.
    GroupMemoryBarrierWithGroupSync();          // transform is done with stg
    for (uint b = tid; b < nbins; b += WG) stg[b] = thrBits;
    GroupMemoryBarrierWithGroupSync();

    uint myMag[16];
    uint myBin[16];
    [unroll] for (uint i = 0; i < R; ++i) {
        uint idx = slotToIndex(tid * R + i);
        bool live = (idx >= winStart && idx < winEnd);
        // Out-of-window samples are set to zero rather than branched around:
        // zero can never beat a seed of >= 0, so the window costs a select
        // and no divergence.
        myMag[i] = live ? asuint(r[i].x*r[i].x + r[i].y*r[i].y) : 0u;
        uint off = idx - winStart;
        // Shift when the binsize is a power of two, divide when it is not --
        // the same split the CPU makes, and the reason no restriction on
        // binsize is needed. A real division here is ~20 cycles.
        myBin[i] = live ? (binShift >= 0 ? (off >> uint(binShift)) : (off / binsize))
                        : 0u;
        if (nbins > 1 && myMag[i] > thrBits)
            InterlockedMax(stg[myBin[i]], myMag[i]);
    }

    // One bin over the whole window is the common case at the small sizes --
    // the CPU has a dedicated binmax_one for it. Every register shares the
    // bin, so they combine in REGISTERS first and the wave reduces once.
    // Reducing per register spends 16 wave operations where 1 will do, and
    // that single change was worth 2.48 -> 2.28 ms at n=4096.
    if (nbins == 1) {
        uint bestBits = thrBits;
        [unroll] for (uint i = 0; i < R; ++i) bestBits = max(bestBits, myMag[i]);
        uint wm = WaveActiveMax(bestBits);
        if (WaveIsFirstLane() && wm > thrBits) InterlockedMax(stg[0], wm);
    }
    GroupMemoryBarrierWithGroupSync();

    // Whoever matches the bin maximum writes it. On an exact tie more than
    // one thread writes, at equal magnitude and different indices; any of
    // them is a correct argmax and the caller was promised no tie-break.
    [unroll] for (uint i = 0; i < R; ++i) {
        if (myMag[i] > thrBits && stg[myBin[i]] == myMag[i]) {
            uint o = pair * nbins + myBin[i];
            peakIdx[o] = int(slotToIndex(tid * R + i));
            peakVal[o] = r[i];
        }
    }
    // Bins nothing cleared: index -1 and a zero value, matching the CPU. No
    // value is offered for a sample that was never chosen.
    for (uint b = tid; b < nbins; b += WG) {
        if (stg[b] == thrBits) {
            uint o = pair * nbins + b;
            peakIdx[o] = -1;
            peakVal[o] = float2(0.0f, 0.0f);
        }
    }
}

[shader("compute")][numthreads(WG,1,1)]
void fusedTierB(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
                StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
                RWStructuredBuffer<int> peakIdx,
                RWStructuredBuffer<float2> peakVal,
                uniform uint ntmpl, uniform uint winStart, uniform uint winEnd,
                uniform uint binsize, uniform int binShift, uniform uint nbins,
                uniform uint thrBits)
{
    filterPair(gid.x, lid.x, data, tmpl, peakIdx, peakVal, ntmpl,
               winStart, winEnd, binsize, binShift, nbins, thrBits);
}

//: The hierarchical refinement, gated ON THE DEVICE.
//:
//: The coarse pass writes its two halves to buffers; this reads them, makes
//: the same decision the CPU makes, and either refines the pair or writes
//: "nothing here" and stops. The gate lives inside the refining kernel
//: rather than in a compaction pass feeding an indirect dispatch, because a
//: workgroup that exits early costs a launch and nothing else.
//:
//: What it buys is that the whole hierarchical filter becomes three
//: dispatches in ONE command buffer with no host in the loop. Reading the
//: coarse result back to choose survivors cost far more than the filtering
//: did: 0.26 ms of kernel work inside a 5.0 ms call at n=16384.
[shader("compute")][numthreads(WG,1,1)]
void gatedTierB(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
                StructuredBuffer<float2> data, StructuredBuffer<float2> tmpl,
                RWStructuredBuffer<int> peakIdx,
                RWStructuredBuffer<float2> peakVal,
                StructuredBuffer<float2> coarse,
                uniform uint ntmpl, uniform uint winStart, uniform uint winEnd,
                uniform uint binsize, uniform int binShift, uniform uint nbins,
                uniform uint thrBits, uniform float thr)
{
    uint pair = gid.x, tid = lid.x;
    // ONE coarse value against ONE threshold. There used to be two buffers
    // and two thresholds: an even half and a half-sample-shifted odd half,
    // with a cheap gate deciding whether the odd transform was worth
    // computing. The coarse grid is critically sampled now -- there is no
    // odd half, so there is nothing for a second threshold to gate, and
    // this is the entire decision the coarse pass exists to make.
    if (length(coarse[pair]) < thr) {
        for (uint b = tid; b < nbins; b += WG) {
            uint o = pair * nbins + b;
            peakIdx[o] = -1;
            peakVal[o] = float2(0.0f, 0.0f);
        }
        return;
    }
    filterPair(pair, tid, data, tmpl, peakIdx, peakVal, ntmpl,
               winStart, winEnd, binsize, binShift, nbins, thrBits);
}
