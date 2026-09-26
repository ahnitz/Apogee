// Extract the coarse band without reading a GPU forward transform on the CPU.
[shader("compute")][numthreads(256,1,1)]
void packCoarse(uint3 tid: SV_DispatchThreadID,
                StructuredBuffer<float2> data,
                RWStructuredBuffer<uint> coarse,
                uniform uint n, uniform uint band,
                uniform uint count, uniform uint packed)
{
    uint i = tid.x;
    if (i >= count) return;
    float2 x = data[(i / band)*n + i % band];
    if (packed != 0)
        coarse[i] = f32tof16(x.x) | (f32tof16(x.y) << 16);
    else {
        coarse[2*i] = asuint(x.x);
        coarse[2*i+1] = asuint(x.y);
    }
}
