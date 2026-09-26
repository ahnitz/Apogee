#include <metal_stdlib>
#include <metal_math>
#include <metal_texture>
using namespace metal;

#line 3 "/tmp/mf-forward-review/src/gpu/pack_coarse.slang"
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

#line 11
    uint _S1 = i_0 / (&kernelContext_0)->entryPointParams_0->band_0;

#line 11
    uint _S2 = _S1 * (&kernelContext_0)->entryPointParams_0->n_0;

#line 11
    uint _S3 = i_0 % (&kernelContext_0)->entryPointParams_0->band_0;

#line 11
    float2 _S4 = float2(*((&kernelContext_0)->entryPointParams_data_0+(_S2 + _S3))) ;
    if(((&kernelContext_0)->entryPointParams_0->packed_0) != 0U)
    {

#line 13
        *((&kernelContext_0)->entryPointParams_coarse_0+i_0) = (as_type<ushort>((half)((_S4.x)))) | ((as_type<ushort>((half)((_S4.y)))) << 16U);

#line 12
    }
    else
    {
        uint _S5 = 2U * i_0;

#line 15
        *((&kernelContext_0)->entryPointParams_coarse_0+_S5) = (as_type<uint>((_S4.x)));
        *((&kernelContext_0)->entryPointParams_coarse_0+(_S5 + 1U)) = (as_type<uint>((_S4.y)));

#line 12
    }

#line 18
    return;
}
