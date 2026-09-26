void forwardTransform(inout C r[RADIX], uint tid)
{
#include "fft_transform.slang"
}

// Appended to tierb.slang by build_forward.py: share its exact butterflies,
// staging exchange, and output permutation. FFT(x)/N = conj(IFFT(conj(x)/N)).
[shader("compute")][numthreads(WG,1,1)]
void seriesForward(uint3 gid: SV_GroupID, uint3 lid: SV_GroupThreadID,
                   StructuredBuffer<float2> series,
                   StructuredBuffer<uint> starts,
                   RWStructuredBuffer<float2> spectra,
                   uniform uint seriesLength)
{
    uint tid = lid.x;
    _tid = tid;
    _stgBase = 0;
    uint start = starts[gid.x];
    C r[RADIX];
    [unroll] for (uint k = 0; k < R; ++k) {
        uint offset = tid + WG*k;
        float2 x = float2(0, 0);
        // Subtraction avoids wraparound for starts beyond the input tail.
        if (start < seriesLength && offset < seriesLength - start)
            x = series[start + offset];
        r[k] = C(x.x / float(N), -x.y / float(N));
    }
    forwardTransform(r, tid);
    [unroll] for (uint k = 0; k < R; ++k) {
        uint index = slotToIndex(tid * R + k);
        spectra[gid.x*N + index] = float2(r[k].x, -r[k].y);
    }
}
