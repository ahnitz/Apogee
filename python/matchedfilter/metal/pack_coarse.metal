#include <metal_stdlib>
#include <metal_math>
#include <metal_texture>
using namespace metal;

#line 11218 "hlsl.meta.slang"
uint firstbithigh_0(uint value_0)
{

#line 11231
    if(value_0 == 0U)
    {

#line 11232
        return 4294967295U;
    }

#line 11233
    uint _S1 = clz(value_0);

#line 11233
    return 31U - _S1;
}


#line 3 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/src/gpu/pack_coarse.slang"
struct EntryPointParams_0
{
    uint n_0;
    uint band_0;
    uint count_0;
    uint packed_0;
};


#line 3
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_data_0;
    uint device* entryPointParams_coarse_0;
};


#line 3
[[kernel]] void packCoarse(uint3 tid_0 [[thread_position_in_grid]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], uint device* entryPointParams_coarse_1 [[buffer(2)]])
{

#line 3
    thread KernelContext_0 kernelContext_0;

#line 3
    (&kernelContext_0)->entryPointParams_0 = entryPointParams_1;

#line 3
    (&kernelContext_0)->entryPointParams_data_0 = entryPointParams_data_1;

#line 3
    (&kernelContext_0)->entryPointParams_coarse_0 = entryPointParams_coarse_1;

#line 9
    uint i_0 = tid_0.x;
    if(i_0 >= (entryPointParams_1->count_0))
    {

#line 10
        return;
    }

#line 10
    float2 _S2 = float2(*((&kernelContext_0)->entryPointParams_data_0+((i_0 >> (firstbithigh_0((&kernelContext_0)->entryPointParams_0->band_0))) * (&kernelContext_0)->entryPointParams_0->n_0 + (i_0 & ((&kernelContext_0)->entryPointParams_0->band_0 - 1U))))) ;


    if(((&kernelContext_0)->entryPointParams_0->packed_0) != 0U)
    {

#line 14
        *((&kernelContext_0)->entryPointParams_coarse_0+i_0) = (as_type<ushort>((half)((_S2.x)))) | ((as_type<ushort>((half)((_S2.y)))) << 16U);

#line 13
    }
    else
    {
        uint _S3 = 2U * i_0;

#line 16
        *((&kernelContext_0)->entryPointParams_coarse_0+_S3) = (as_type<uint>((_S2.x)));
        *((&kernelContext_0)->entryPointParams_coarse_0+(_S3 + 1U)) = (as_type<uint>((_S2.y)));

#line 13
    }

#line 19
    return;
}
