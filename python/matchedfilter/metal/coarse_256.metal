#include <metal_stdlib>
#include <metal_math>
#include <metal_texture>
using namespace metal;

#line 69 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/spirv/ct_256_m.slang"
float2 cmulConj_0(float2 a_0, float2 b_0)
{

#line 69
    float _S1 = a_0.x;

#line 69
    float _S2 = b_0.x;

#line 69
    float _S3 = a_0.y;

#line 69
    float _S4 = b_0.y;

#line 69
    return float2(_S1 * _S2 + _S3 * _S4, _S3 * _S2 - _S1 * _S4);
}


#line 71
void r4_0(float2 thread* a_1, float2 thread* b_1, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_1 + *c_0;

#line 73
    float2 t1_0 = *a_1 - *c_0;

#line 73
    float2 t2_0 = *b_1 + *d_0;

#line 73
    float2 t3_0 = *b_1 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_1 = t0_0 + t2_0;

#line 75
    *b_1 = t1_0 + j3_0;

#line 75
    *c_0 = t0_0 - t2_0;

#line 75
    *d_0 = t1_0 - j3_0;
    return;
}


#line 68
float2 cmul_0(float2 a_2, float2 b_2)
{

#line 68
    float _S5 = a_2.x;

#line 68
    float _S6 = b_2.x;

#line 68
    float _S7 = a_2.y;

#line 68
    float _S8 = b_2.y;

#line 68
    return float2(_S5 * _S6 - _S7 * _S8, _S5 * _S8 + _S7 * _S6);
}


#line 77
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 84
    uint n1_0 = 0U;
    for(;;)
    {

#line 85
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 85
            break;
        }

#line 85
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 85
        n1_0 = n1_0 + 1U;

#line 85
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 86
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 86
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 87
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 87
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 88
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 88
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 88
    uint k2_0 = 0U;
    for(;;)
    {

#line 89
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 89
            break;
        }

#line 89
        uint _S9 = 4U * k2_0;

#line 89
        r4_0(&(*r_0)[_S9], &(*r_0)[_S9 + 1U], &(*r_0)[_S9 + 2U], &(*r_0)[_S9 + 3U]);

#line 89
        k2_0 = k2_0 + 1U;

#line 89
    }

    float2 t_0 = (*r_0)[int(1)];

#line 91
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 91
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 92
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 92
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 93
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 93
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 94
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 94
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 95
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 95
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 96
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 96
    (*r_0)[int(14)] = t_5;
    return;
}


#line 122
void dftR_0(array<float2, int(16)> thread* r_1)
{

    dft16_0(r_1);



    return;
}


#line 136
void stage2_0(array<float2, int(16)> thread* r_2)
{

    dft16_0(r_2);

#line 153
    return;
}


#line 90 "core"
struct EntryPointParams_0
{
    uint ntmpl_0;
    uint npairs_0;
};


#line 181 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/spirv/ct_256_m.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_data_0;
    packed_float2 device* entryPointParams_tmpl_0;
    packed_float2 device* entryPointParams_out_0;
    array<float2, int(1024)> threadgroup* sh_0;
};


#line 158
[[kernel]] void coarseTile(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], packed_float2 device* entryPointParams_out_1 [[buffer(3)]])
{

#line 158
    thread KernelContext_0 kernelContext_0;

#line 158
    (&kernelContext_0)->entryPointParams_0 = entryPointParams_1;

#line 158
    (&kernelContext_0)->entryPointParams_data_0 = entryPointParams_data_1;

#line 158
    (&kernelContext_0)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 158
    (&kernelContext_0)->entryPointParams_out_0 = entryPointParams_out_1;

#line 158
    threadgroup array<float2, int(1024)> sh_1;

#line 158
    (&kernelContext_0)->sh_0 = &sh_1;

#line 163
    uint tid_0 = lid_0.x;

#line 163
    uint slot_0 = tid_0 / 16U;

#line 163
    uint lane_0 = tid_0 % 16U;
    uint pair_0 = gid_0.x * 4U + slot_0;
    uint base_0 = slot_0 * 256U;
    if(pair_0 >= (entryPointParams_1->npairs_0))
    {

#line 166
        return;
    }

#line 167
    uint _S10 = pair_0 / (&kernelContext_0)->entryPointParams_0->ntmpl_0;

#line 167
    uint _S11 = pair_0 % (&kernelContext_0)->entryPointParams_0->ntmpl_0;

    thread array<float2, int(16)> r_3;

#line 169
    uint i_0 = 0U;
    for(;;)
    {

#line 170
        if(i_0 < 16U)
        {
        }
        else
        {

#line 170
            break;
        }

#line 171
        uint k_0 = lane_0 + 16U * i_0;
        r_3[i_0] = cmulConj_0(float2(*((&kernelContext_0)->entryPointParams_data_0+(_S10 * 256U + k_0))) , float2(*((&kernelContext_0)->entryPointParams_tmpl_0+(_S11 * 256U + k_0))) );

#line 170
        i_0 = i_0 + 1U;

#line 170
    }



    dftR_0(&r_3);

#line 174
    uint k2_1 = 0U;
    for(;;)
    {

#line 175
        if(k2_1 < 16U)
        {
        }
        else
        {

#line 175
            break;
        }

#line 176
        float ang_0 = 6.28318548202514648f * float(lane_0 * k2_1) / 256.0f;
        r_3[k2_1] = cmul_0(r_3[k2_1], float2(cos(ang_0), sin(ang_0)));

#line 175
        k2_1 = k2_1 + 1U;

#line 175
    }

#line 180
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 180
    i_0 = 0U;
    for(;;)
    {

#line 181
        if(i_0 < 16U)
        {
        }
        else
        {

#line 181
            break;
        }

#line 181
        (*(&kernelContext_0)->sh_0)[base_0 + i_0 * 16U + lane_0] = r_3[i_0];

#line 181
        i_0 = i_0 + 1U;

#line 181
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 182
    i_0 = 0U;
    for(;;)
    {

#line 183
        if(i_0 < 16U)
        {
        }
        else
        {

#line 183
            break;
        }

#line 183
        r_3[i_0] = (*(&kernelContext_0)->sh_0)[base_0 + lane_0 * 16U + i_0];

#line 183
        i_0 = i_0 + 1U;

#line 183
    }
    stage2_0(&r_3);

#line 184
    float best_0 = 0.0f;

#line 184
    i_0 = 0U;


    for(;;)
    {

#line 187
        if(i_0 < 16U)
        {
        }
        else
        {

#line 187
            break;
        }

#line 187
        float _S12 = max(best_0, r_3[i_0].x * r_3[i_0].x + r_3[i_0].y * r_3[i_0].y);

#line 187
        uint i_1 = i_0 + 1U;

#line 187
        best_0 = _S12;

#line 187
        i_0 = i_1;

#line 187
    }



    threadgroup_barrier(mem_flags::mem_threadgroup);
    uint _S13 = base_0 + lane_0;

#line 192
    (*(&kernelContext_0)->sh_0)[_S13] = float2(best_0, 0.0f);
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 193
    uint st_0 = 8U;
    for(;;)
    {

#line 194
        if(st_0 > 0U)
        {
        }
        else
        {

#line 194
            break;
        }

#line 195
        if(lane_0 < st_0)
        {

#line 195
            (*(&kernelContext_0)->sh_0)[_S13] = float2(max((*(&kernelContext_0)->sh_0)[_S13].x, (*(&kernelContext_0)->sh_0)[_S13 + st_0].x), 0.0f);

#line 195
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 194
        st_0 = st_0 >> 1U;

#line 194
    }

#line 202
    if(lane_0 == 0U)
    {

#line 202
        *((&kernelContext_0)->entryPointParams_out_0+pair_0) = packed_float2(float2(sqrt((*(&kernelContext_0)->sh_0)[base_0].x), 0.0f)) ;

#line 202
    }
    return;
}

