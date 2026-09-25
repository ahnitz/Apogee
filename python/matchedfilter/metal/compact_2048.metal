#include <metal_stdlib>
#include <metal_math>
#include <metal_texture>
using namespace metal;

#line 90 "core"
struct EntryPointParams_0
{
    uint pairs_0;
    float thr_0;
};


#line 403 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_2048_compactPairs.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_coarse_0;
    uint device* entryPointParams_survivors_0;
    uint device* entryPointParams_args_0;
};


#line 403
[[kernel]] void compactPairs(uint3 gid_0 [[thread_position_in_grid]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_coarse_1 [[buffer(1)]], uint device* entryPointParams_survivors_1 [[buffer(2)]], uint device* entryPointParams_args_1 [[buffer(3)]])
{

#line 403
    thread KernelContext_0 kernelContext_0;

#line 403
    (&kernelContext_0)->entryPointParams_0 = entryPointParams_1;

#line 403
    (&kernelContext_0)->entryPointParams_coarse_0 = entryPointParams_coarse_1;

#line 403
    (&kernelContext_0)->entryPointParams_survivors_0 = entryPointParams_survivors_1;

#line 403
    (&kernelContext_0)->entryPointParams_args_0 = entryPointParams_args_1;

#line 409
    uint pair_0 = gid_0.x;
    if(pair_0 >= (entryPointParams_1->pairs_0))
    {

#line 410
        return;
    }

#line 411
    if((length(float2(*((&kernelContext_0)->entryPointParams_coarse_0+pair_0)) )) < ((&kernelContext_0)->entryPointParams_0->thr_0))
    {

#line 411
        return;
    }
    uint slot_0 = atomic_fetch_add_explicit(((atomic_uint device*)((&kernelContext_0)->entryPointParams_args_0+int(0))), 1U, memory_order_relaxed);
    *((&kernelContext_0)->entryPointParams_survivors_0+slot_0) = pair_0;
    return;
}

