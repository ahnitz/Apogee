#include <metal_stdlib>
#include <metal_math>
#include <metal_texture>
using namespace metal;

#line 90 "core"
struct EntryPointParams_0
{
    uint pairs_0;
    float thr_0;
    uint nbins_0;
};


#line 866 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_512_compactPairs.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_coarse_0;
    uint device* entryPointParams_survivors_0;
    uint device* entryPointParams_args_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
};


#line 866
[[kernel]] void compactPairs(uint3 gid_0 [[thread_position_in_grid]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_coarse_1 [[buffer(1)]], uint device* entryPointParams_survivors_1 [[buffer(2)]], uint device* entryPointParams_args_1 [[buffer(3)]], int device* entryPointParams_peakIdx_1 [[buffer(4)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(5)]])
{

#line 866
    thread KernelContext_0 kernelContext_0;

#line 866
    (&kernelContext_0)->entryPointParams_0 = entryPointParams_1;

#line 866
    (&kernelContext_0)->entryPointParams_coarse_0 = entryPointParams_coarse_1;

#line 866
    (&kernelContext_0)->entryPointParams_survivors_0 = entryPointParams_survivors_1;

#line 866
    (&kernelContext_0)->entryPointParams_args_0 = entryPointParams_args_1;

#line 866
    (&kernelContext_0)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 866
    (&kernelContext_0)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 874
    uint pair_0 = gid_0.x;
    if(pair_0 >= (entryPointParams_1->pairs_0))
    {

#line 875
        return;
    }

#line 876
    if((length(float2(*((&kernelContext_0)->entryPointParams_coarse_0+pair_0)) )) >= ((&kernelContext_0)->entryPointParams_0->thr_0))
    {
        uint slot_0 = atomic_fetch_add_explicit(((atomic_uint device*)((&kernelContext_0)->entryPointParams_args_0+int(0))), 1U, memory_order_relaxed);
        *((&kernelContext_0)->entryPointParams_survivors_0+slot_0) = pair_0;
        return;
    }

#line 880
    uint b_0 = 0U;

#line 887
    for(;;)
    {

#line 887
        if(b_0 < ((&kernelContext_0)->entryPointParams_0->nbins_0))
        {
        }
        else
        {

#line 887
            break;
        }

#line 888
        uint o_0 = pair_0 * (&kernelContext_0)->entryPointParams_0->nbins_0 + b_0;
        *((&kernelContext_0)->entryPointParams_peakIdx_0+o_0) = int(-1);

#line 889
        *((&kernelContext_0)->entryPointParams_peakVal_0+o_0) = packed_float2(float2(0.0f, 0.0f)) ;

#line 887
        b_0 = b_0 + 1U;

#line 887
    }

#line 892
    return;
}

