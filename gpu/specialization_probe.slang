// Can a constant be left open in the shipped blob and fixed at pipeline
// creation from what the device reports?
[SpecializationConstant] const uint LANES = 32;   // queried subgroup width
[SpecializationConstant] const uint CHUNK = 4;    // staging chunk
[SpecializationConstant] const uint NLEV  = 2;    // levels to unroll

groupshared float2 stg[1024];

[shader("compute")][numthreads(256,1,1)]
void spec(uint3 tid: SV_DispatchThreadID, uint3 lid: SV_GroupThreadID,
          RWStructuredBuffer<float> o)
{
    float acc = 0.0f;
    // a loop whose trip count is a specialization constant
    for (uint c = 0; c < 16 / CHUNK; ++c)
        for (uint l = 0; l < NLEV; ++l)
            acc += float(c * l);
    // a branch on the queried wave width, as the transpose does
    if (LANES >= 16) acc += WaveActiveMax(acc);
    else { stg[lid.x] = float2(acc, 0); GroupMemoryBarrierWithGroupSync(); acc += stg[0].x; }
    o[tid.x] = acc;
}
