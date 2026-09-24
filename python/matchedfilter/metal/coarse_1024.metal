#include <metal_stdlib>
#include <metal_math>
#include <metal_texture>
using namespace metal;

#line 61 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/spirv/ct_1024_m.slang"
float2 cmulConj_0(float2 a_0, float2 b_0)
{

#line 61
    float _S1 = a_0.x;

#line 61
    float _S2 = b_0.x;

#line 61
    float _S3 = a_0.y;

#line 61
    float _S4 = b_0.y;

#line 61
    return float2(_S1 * _S2 + _S3 * _S4, _S3 * _S2 - _S1 * _S4);
}


#line 63
void r4_0(float2 thread* a_1, float2 thread* b_1, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_1 + *c_0;

#line 65
    float2 t1_0 = *a_1 - *c_0;

#line 65
    float2 t2_0 = *b_1 + *d_0;

#line 65
    float2 t3_0 = *b_1 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_1 = t0_0 + t2_0;

#line 67
    *b_1 = t1_0 + j3_0;

#line 67
    *c_0 = t0_0 - t2_0;

#line 67
    *d_0 = t1_0 - j3_0;
    return;
}


#line 60
float2 cmul_0(float2 a_2, float2 b_2)
{

#line 60
    float _S5 = a_2.x;

#line 60
    float _S6 = b_2.x;

#line 60
    float _S7 = a_2.y;

#line 60
    float _S8 = b_2.y;

#line 60
    return float2(_S5 * _S6 - _S7 * _S8, _S5 * _S8 + _S7 * _S6);
}


#line 69
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639, 0.38268342614173889);
    float2 W2_0 = float2(0.70710676908493042, 0.70710676908493042);
    float2 W3_0 = float2(0.38268342614173889, 0.92387950420379639);
    float2 W4_0 = float2(0.0, 1.0);
    float2 W6_0 = float2(-0.70710676908493042, 0.70710676908493042);
    float2 W9_0 = float2(-0.92387950420379639, -0.38268342614173889);

#line 76
    uint n1_0 = 0U;
    for(;;)
    {

#line 77
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 77
            break;
        }

#line 77
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 77
        n1_0 = n1_0 + 1U;

#line 77
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 78
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 78
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 79
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 79
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 80
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 80
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 80
    uint k2_0 = 0U;
    for(;;)
    {

#line 81
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 81
            break;
        }

#line 81
        uint _S9 = 4U * k2_0;

#line 81
        r4_0(&(*r_0)[_S9], &(*r_0)[_S9 + 1U], &(*r_0)[_S9 + 2U], &(*r_0)[_S9 + 3U]);

#line 81
        k2_0 = k2_0 + 1U;

#line 81
    }

    float2 t_0 = (*r_0)[int(1)];

#line 83
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 83
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 84
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 84
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 85
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 85
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 86
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 86
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 87
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 87
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 88
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 88
    (*r_0)[int(14)] = t_5;
    return;
}


#line 99
void dft32_0(array<float2, int(32)> thread* r_1)
{
    thread array<float2, int(16)> e_0;

#line 101
    thread array<float2, int(16)> o_0;

#line 101
    uint i_0 = 0U;
    for(;;)
    {

#line 102
        if(i_0 < 16U)
        {
        }
        else
        {

#line 102
            break;
        }

#line 102
        uint _S10 = 2U * i_0;

#line 102
        e_0[i_0] = (*r_1)[_S10];

#line 102
        o_0[i_0] = (*r_1)[_S10 + 1U];

#line 102
        i_0 = i_0 + 1U;

#line 102
    }
    dft16_0(&e_0);
    dft16_0(&o_0);

#line 104
    uint k_0 = 0U;
    for(;;)
    {

#line 105
        if(k_0 < 16U)
        {
        }
        else
        {

#line 105
            break;
        }

#line 106
        float ang_0 = 6.28318548202514648 * float(k_0) / 32.0;
        float2 w_0 = cmul_0(o_0[k_0], float2(cos(ang_0), sin(ang_0)));
        (*r_1)[k_0] = e_0[k_0] + w_0;
        (*r_1)[k_0 + 16U] = e_0[k_0] - w_0;

#line 105
        k_0 = k_0 + 1U;

#line 105
    }

#line 111
    return;
}

void dftR_0(array<float2, int(32)> thread* r_2)
{



    dft32_0(r_2);

    return;
}


#line 128
void stage2_0(array<float2, int(32)> thread* r_3)
{

#line 143
    dft32_0(r_3);

    return;
}


#line 90 "core"
struct EntryPointParams_0
{
    uint ntmpl_0;
    uint npairs_0;
};


#line 173 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/spirv/ct_1024_m.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_data_0;
    packed_float2 device* entryPointParams_tmpl_0;
    packed_float2 device* entryPointParams_out_0;
    array<float2, int(4096)> threadgroup* sh_0;
};


#line 150
[[kernel]] void coarseTile(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], packed_float2 device* entryPointParams_out_1 [[buffer(3)]])
{

#line 150
    thread KernelContext_0 kernelContext_0;

#line 150
    (&kernelContext_0)->entryPointParams_0 = entryPointParams_1;

#line 150
    (&kernelContext_0)->entryPointParams_data_0 = entryPointParams_data_1;

#line 150
    (&kernelContext_0)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 150
    (&kernelContext_0)->entryPointParams_out_0 = entryPointParams_out_1;

#line 150
    threadgroup array<float2, int(4096)> sh_1;

#line 150
    (&kernelContext_0)->sh_0 = &sh_1;

#line 155
    uint tid_0 = lid_0.x;

#line 155
    uint slot_0 = tid_0 / 32U;

#line 155
    uint lane_0 = tid_0 % 32U;
    uint pair_0 = gid_0.x * 4U + slot_0;
    uint base_0 = slot_0 * 1024U;
    if(pair_0 >= (entryPointParams_1->npairs_0))
    {

#line 158
        return;
    }

#line 159
    uint _S11 = pair_0 / (&kernelContext_0)->entryPointParams_0->ntmpl_0;

#line 159
    uint _S12 = pair_0 % (&kernelContext_0)->entryPointParams_0->ntmpl_0;

    thread array<float2, int(32)> r_4;

#line 161
    uint i_1 = 0U;
    for(;;)
    {

#line 162
        if(i_1 < 32U)
        {
        }
        else
        {

#line 162
            break;
        }

#line 163
        uint k_1 = lane_0 + 32U * i_1;
        r_4[i_1] = cmulConj_0(float2(*((&kernelContext_0)->entryPointParams_data_0+(_S11 * 1024U + k_1))) , float2(*((&kernelContext_0)->entryPointParams_tmpl_0+(_S12 * 1024U + k_1))) );

#line 162
        i_1 = i_1 + 1U;

#line 162
    }



    dftR_0(&r_4);

#line 166
    uint k2_1 = 0U;
    for(;;)
    {

#line 167
        if(k2_1 < 32U)
        {
        }
        else
        {

#line 167
            break;
        }

#line 168
        float ang_1 = 6.28318548202514648 * float(lane_0 * k2_1) / 1024.0;
        r_4[k2_1] = cmul_0(r_4[k2_1], float2(cos(ang_1), sin(ang_1)));

#line 167
        k2_1 = k2_1 + 1U;

#line 167
    }

#line 172
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 172
    i_1 = 0U;
    for(;;)
    {

#line 173
        if(i_1 < 32U)
        {
        }
        else
        {

#line 173
            break;
        }

#line 173
        (*(&kernelContext_0)->sh_0)[base_0 + i_1 * 32U + lane_0] = r_4[i_1];

#line 173
        i_1 = i_1 + 1U;

#line 173
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 174
    i_1 = 0U;
    for(;;)
    {

#line 175
        if(i_1 < 32U)
        {
        }
        else
        {

#line 175
            break;
        }

#line 175
        r_4[i_1] = (*(&kernelContext_0)->sh_0)[base_0 + lane_0 * 32U + i_1];

#line 175
        i_1 = i_1 + 1U;

#line 175
    }
    stage2_0(&r_4);

#line 176
    float best_0 = 0.0;

#line 176
    i_1 = 0U;


    for(;;)
    {

#line 179
        if(i_1 < 32U)
        {
        }
        else
        {

#line 179
            break;
        }

#line 179
        float _S13 = max(best_0, r_4[i_1].x * r_4[i_1].x + r_4[i_1].y * r_4[i_1].y);

#line 179
        uint i_2 = i_1 + 1U;

#line 179
        best_0 = _S13;

#line 179
        i_1 = i_2;

#line 179
    }



    threadgroup_barrier(mem_flags::mem_threadgroup);
    uint _S14 = base_0 + lane_0;

#line 184
    (*(&kernelContext_0)->sh_0)[_S14] = float2(best_0, 0.0);
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 185
    uint st_0 = 16U;
    for(;;)
    {

#line 186
        if(st_0 > 0U)
        {
        }
        else
        {

#line 186
            break;
        }

#line 187
        if(lane_0 < st_0)
        {

#line 187
            (*(&kernelContext_0)->sh_0)[_S14] = float2(max((*(&kernelContext_0)->sh_0)[_S14].x, (*(&kernelContext_0)->sh_0)[_S14 + st_0].x), 0.0);

#line 187
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 186
        st_0 = st_0 >> 1U;

#line 186
    }

#line 194
    if(lane_0 == 0U)
    {

#line 194
        *((&kernelContext_0)->entryPointParams_out_0+pair_0) = packed_float2(float2(sqrt((*(&kernelContext_0)->sh_0)[base_0].x), 0.0)) ;

#line 194
    }
    return;
}

