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


#line 333 "/tmp/tmp3uk57uby/forward.slang"
void r4_0(float2 thread* a_0, float2 thread* b_0, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_0 + *c_0;

#line 335
    float2 t1_0 = *a_0 - *c_0;

#line 335
    float2 t2_0 = *b_0 + *d_0;

#line 335
    float2 t3_0 = *b_0 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_0 = t0_0 + t2_0;

#line 337
    *b_0 = t1_0 + j3_0;

#line 337
    *c_0 = t0_0 - t2_0;

#line 337
    *d_0 = t1_0 - j3_0;
    return;
}


#line 183
float2 cmul_0(float2 a_1, float2 b_1)
{

#line 183
    float _S2 = a_1.x;

#line 183
    float _S3 = b_1.x;

#line 183
    float _S4 = a_1.y;

#line 183
    float _S5 = b_1.y;

#line 183
    return float2(_S2 * _S3 - _S4 * _S5, _S2 * _S5 + _S4 * _S3);
}


#line 369
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 376
    uint n1_0 = 0U;
    for(;;)
    {

#line 377
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 377
            break;
        }

#line 377
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 377
        n1_0 = n1_0 + 1U;

#line 377
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 378
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 378
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 379
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 379
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 380
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 380
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 380
    uint k2_0 = 0U;
    for(;;)
    {

#line 381
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 381
            break;
        }

#line 381
        uint _S6 = 4U * k2_0;

#line 381
        r4_0(&(*r_0)[_S6], &(*r_0)[_S6 + 1U], &(*r_0)[_S6 + 2U], &(*r_0)[_S6 + 3U]);

#line 381
        k2_0 = k2_0 + 1U;

#line 381
    }

    float2 t_0 = (*r_0)[int(1)];

#line 383
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 383
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 384
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 384
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 385
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 385
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 386
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 386
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 387
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 387
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 388
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 388
    (*r_0)[int(14)] = t_5;
    return;
}


#line 90 "core"
struct EntryPointParams_0
{
    uint seriesLength_0;
};


#line 172 "/tmp/tmp3uk57uby/forward.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_series_0;
    uint device* entryPointParams_starts_0;
    packed_float2 device* entryPointParams_spectra_0;
    uint _tid_0;
    uint _stgBase_0;
    array<uint, int(8192)> threadgroup* stg_0;
};


#line 172
void stgPut_0(uint i_0, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 172
    uint _S7 = 2U * i_0;

#line 172
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S7] = (as_type<uint>((v_0.x)));

#line 172
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S7 + 1U] = (as_type<uint>((v_0.y)));

#line 172
    return;
}


#line 173
float2 stgGet_0(uint i_1, KernelContext_0 thread* kernelContext_1)
{

#line 173
    uint _S8 = 2U * i_1;

#line 173
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S8]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S8 + 1U]))));
}


#line 494
void exchange_0(array<float2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 494
    uint j_0;

#line 505
    thread array<float2, int(16)> out_0;

#line 505
    uint z_0 = 0U;
    for(;;)
    {

#line 506
        if(z_0 < 16U)
        {
        }
        else
        {

#line 506
            break;
        }

#line 506
        out_0[z_0] = float2(0.0f, 0.0f);

#line 506
        z_0 = z_0 + 1U;

#line 506
    }
    uint _S9 = (1U << lgSpan_0) - 1U;
    uint _S10 = (1U << lgLen_0) - 1U;

#line 508
    uint c_1 = 0U;
    for(;;)
    {

#line 509
        if(c_1 < 2U)
        {
        }
        else
        {

#line 509
            break;
        }

#line 510
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 510
        j_0 = 0U;
        for(;;)
        {

#line 511
            if(j_0 < 8U)
            {
            }
            else
            {

#line 511
                break;
            }

#line 511
            stgPut_0(j_0 * 512U + kernelContext_2->_tid_0, (*r_1)[c_1 * 8U + j_0], kernelContext_2);

#line 511
            j_0 = j_0 + 1U;

#line 511
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 512
        uint d_1 = 0U;
        for(;;)
        {

#line 513
            if(d_1 < 16U)
            {
            }
            else
            {

#line 513
                break;
            }
            uint b_2 = ((*want_0)[d_1]) >> lgLen_0;

#line 515
            uint rem_0 = ((*want_0)[d_1]) & _S10;
            uint i_2 = rem_0 >> lgSpan_0;

#line 516
            uint ln_0 = rem_0 & _S9;
            uint _S11 = c_1 * 8U;

#line 517
            bool _S12;

#line 517
            if(i_2 >= _S11)
            {

#line 517
                _S12 = i_2 < ((c_1 + 1U) * 8U);

#line 517
            }
            else
            {

#line 517
                _S12 = false;

#line 517
            }

#line 517
            if(_S12)
            {

#line 517
                float2 _S13 = stgGet_0((i_2 - _S11) * 512U + (b_2 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S13;

#line 517
            }

#line 513
            d_1 = d_1 + 1U;

#line 513
        }

#line 509
        c_1 = c_1 + 1U;

#line 509
    }

#line 509
    j_0 = 0U;

#line 521
    for(;;)
    {

#line 521
        if(j_0 < 16U)
        {
        }
        else
        {

#line 521
            break;
        }

#line 521
        (*r_1)[j_0] = out_0[j_0];

#line 521
        j_0 = j_0 + 1U;

#line 521
    }
    return;
}


#line 344
void dft2_0(array<float2, int(16)> thread* r_2, uint o_0)
{
    float2 a_2 = (*r_2)[o_0];

#line 346
    float2 b_3 = (*r_2)[o_0 + 1U];

#line 346
    (*r_2)[o_0] = (*r_2)[o_0] + (*r_2)[o_0 + 1U];

#line 346
    (*r_2)[o_0 + 1U] = a_2 - b_3;
    return;
}


#line 472
void innermost_0(array<float2, int(16)> thread* r_3)
{

#line 472
    uint b_4 = 0U;

#line 482
    for(;;)
    {

#line 482
        if(b_4 < 8U)
        {
        }
        else
        {

#line 482
            break;
        }

#line 482
        dft2_0(r_3, b_4 * 2U);

#line 482
        b_4 = b_4 + 1U;

#line 482
    }

    return;
}


#line 1146
void forwardTransform_0(array<float2, int(16)> thread* r_4, uint tid_0, KernelContext_0 thread* kernelContext_3)
{

#line 1146
    uint z_1;

#line 1146
    uint _S14;

#line 1146
    uint k2_1;

#line 1146
    float cr_0;

#line 1146
    float ci_0;

#line 1146
    uint _S15;

#line 1146
    uint d_2;

#line 1146
    uint _S16;

#line 1146
    uint _S17;

#line 1146
    for(;;)
    {

#line 1146
        for(;;)
        {

#line 7 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/src/gpu/fft_transform.slang"
            for(;;)
            {

#line 8
                thread array<uint, int(16)> want_1;

#line 8
                z_1 = 0U;
                for(;;)
                {

#line 9
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 9
                        break;
                    }

#line 9
                    want_1[z_1] = 0U;

#line 9
                    z_1 = z_1 + 1U;

#line 9
                }



                uint lgTB_0 = firstbithigh_0(512U);

#line 13
                _S14 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(8192U);

                uint lane_0 = tid_0 & 511U;


                dft16_0(r_4);

#line 27
                float a1_0 = 6.28318548202514648f * float(lane_0) / 8192.0f;
                float _S18 = cos(a1_0);

#line 28
                float _S19 = sin(a1_0);

#line 28
                k2_1 = 0U;

#line 28
                cr_0 = 1.0f;

#line 28
                ci_0 = 0.0f;

                for(;;)
                {

#line 30
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 30
                        break;
                    }

#line 31
                    (*r_4)[k2_1] = cmul_0((*r_4)[k2_1], float2(cr_0, ci_0));
                    float nr_0 = cr_0 * _S18 - ci_0 * _S19;
                    float _S20 = cr_0 * _S19 + ci_0 * _S18;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_0;

#line 30
                    ci_0 = _S20;

#line 30
                }

#line 40
                uint _S21 = max(512U, 1U);

#line 40
                uint _S22 = 16U / _S21;
                uint _S23 = max(32U, 1U);

#line 41
                _S15 = _S23;
                uint _S24 = tid_0 / _S23;

#line 42
                uint _S25 = tid_0 % _S23;

#line 42
                d_2 = 0U;
                for(;;)
                {

#line 43
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 43
                        break;
                    }

#line 44
                    uint j_1 = d_2 / _S21;

#line 44
                    uint m_0 = d_2 % _S21;
                    want_1[d_2] = _S24 * 512U + _S25 + _S23 * d_2;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(16)> _S26 = want_1;

#line 43
                exchange_0(r_4, &_S26, lgLn_0, lgTB_0, kernelContext_3);

#line 7
                break;
            }

#line 7
            break;
        }

#line 7
        for(;;)
        {

#line 7
            for(;;)
            {

#line 8
                thread array<uint, int(16)> want_2;

#line 8
                z_1 = 0U;
                for(;;)
                {

#line 9
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 9
                        break;
                    }

#line 9
                    want_2[z_1] = 0U;

#line 9
                    z_1 = z_1 + 1U;

#line 9
                }



                uint lgTB_1 = firstbithigh_0(32U);

#line 13
                _S16 = lgTB_1;


                uint lane_1 = tid_0 & 31U;


                dft16_0(r_4);

#line 27
                float a1_1 = 6.28318548202514648f * float(lane_1) / 512.0f;
                float _S27 = cos(a1_1);

#line 28
                float _S28 = sin(a1_1);

#line 28
                k2_1 = 0U;

#line 28
                cr_0 = 1.0f;

#line 28
                ci_0 = 0.0f;

                for(;;)
                {

#line 30
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 30
                        break;
                    }

#line 31
                    (*r_4)[k2_1] = cmul_0((*r_4)[k2_1], float2(cr_0, ci_0));
                    float nr_1 = cr_0 * _S27 - ci_0 * _S28;
                    float _S29 = cr_0 * _S28 + ci_0 * _S27;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_1;

#line 30
                    ci_0 = _S29;

#line 30
                }

#line 40
                uint _S30 = 16U / _S15;
                uint _S31 = max(2U, 1U);

#line 41
                _S17 = _S31;
                uint _S32 = tid_0 / _S31;

#line 42
                uint _S33 = tid_0 % _S31;

#line 42
                d_2 = 0U;
                for(;;)
                {

#line 43
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 43
                        break;
                    }

#line 44
                    uint j_2 = d_2 / _S15;

#line 44
                    uint m_1 = d_2 % _S15;
                    want_2[d_2] = _S32 * 32U + _S33 + _S31 * d_2;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(16)> _S34 = want_2;

#line 43
                exchange_0(r_4, &_S34, _S14, lgTB_1, kernelContext_3);

#line 7
                break;
            }

#line 7
            break;
        }

#line 7
        for(;;)
        {

#line 7
            for(;;)
            {

#line 8
                thread array<uint, int(16)> want_3;

#line 8
                z_1 = 0U;
                for(;;)
                {

#line 9
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 9
                        break;
                    }

#line 9
                    want_3[z_1] = 0U;

#line 9
                    z_1 = z_1 + 1U;

#line 9
                }



                uint lgTB_2 = firstbithigh_0(2U);

                uint _S35 = tid_0 >> lgTB_2;
                uint lane_2 = tid_0 & 1U;


                dft16_0(r_4);

#line 27
                float a1_2 = 6.28318548202514648f * float(lane_2) / 32.0f;
                float _S36 = cos(a1_2);

#line 28
                float _S37 = sin(a1_2);

#line 28
                k2_1 = 0U;

#line 28
                cr_0 = 1.0f;

#line 28
                ci_0 = 0.0f;

                for(;;)
                {

#line 30
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 30
                        break;
                    }

#line 31
                    (*r_4)[k2_1] = cmul_0((*r_4)[k2_1], float2(cr_0, ci_0));
                    float nr_2 = cr_0 * _S36 - ci_0 * _S37;
                    float _S38 = cr_0 * _S37 + ci_0 * _S36;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_2;

#line 30
                    ci_0 = _S38;

#line 30
                }

#line 40
                uint _S39 = 16U / _S17;
                uint _S40 = max(0U, 1U);
                uint _S41 = tid_0 / _S40;

#line 42
                uint _S42 = tid_0 % _S40;

#line 42
                d_2 = 0U;
                for(;;)
                {

#line 43
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 43
                        break;
                    }

#line 44
                    uint j_3 = d_2 / _S17;

#line 44
                    uint m_2 = d_2 % _S17;
                    want_3[d_2] = _S35 * 32U + (lane_2 * _S39 + j_3) * 2U + m_2;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(16)> _S43 = want_3;

#line 43
                exchange_0(r_4, &_S43, _S16, lgTB_2, kernelContext_3);

#line 7
                break;
            }

#line 7
            break;
        }

#line 7
        break;
    }

#line 51
    innermost_0(r_4);

#line 1149 "/tmp/tmp3uk57uby/forward.slang"
    return;
}


#line 545
uint lgOf_0(uint i_3)
{

#line 545
    uint _S44;

#line 545
    if(i_3 < 3U)
    {

#line 545
        _S44 = 4U;

#line 545
    }
    else
    {

#line 545
        _S44 = 1U;

#line 545
    }

#line 545
    return _S44;
}


#line 547
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(3U);

    uint x_0 = slot_0 >> lg_0;

#line 551
    uint lg_1 = lgOf_0(2U);

    uint x_1 = x_0 >> lg_1;

#line 551
    uint lg_2 = lgOf_0(1U);

#line 551
    uint lg_3 = lgOf_0(0U);

#line 556
    return (((((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | (x_1 & ((1U << lg_2) - 1U))) << lg_3) | ((x_1 >> lg_2) & ((1U << lg_3) - 1U));
}


#line 1154
[[kernel]] void seriesForward(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_series_1 [[buffer(1)]], uint device* entryPointParams_starts_1 [[buffer(2)]], packed_float2 device* entryPointParams_spectra_1 [[buffer(3)]])
{

#line 1154
    thread KernelContext_0 kernelContext_4;

#line 1154
    (&kernelContext_4)->entryPointParams_0 = entryPointParams_1;

#line 1154
    (&kernelContext_4)->entryPointParams_series_0 = entryPointParams_series_1;

#line 1154
    (&kernelContext_4)->entryPointParams_starts_0 = entryPointParams_starts_1;

#line 1154
    (&kernelContext_4)->entryPointParams_spectra_0 = entryPointParams_spectra_1;

#line 1154
    threadgroup array<uint, int(8192)> stg_1;

#line 1154
    (&kernelContext_4)->stg_0 = &stg_1;

#line 1160
    uint tid_1 = lid_0.x;
    (&kernelContext_4)->_tid_0 = tid_1;
    (&kernelContext_4)->_stgBase_0 = 0U;
    uint _S45 = gid_0.x;

#line 1163
    uint _S46 = entryPointParams_starts_1[_S45];
    thread array<float2, int(16)> r_5;

#line 1164
    uint k_0 = 0U;
    for(;;)
    {

#line 1165
        if(k_0 < 16U)
        {
        }
        else
        {

#line 1165
            break;
        }

#line 1166
        uint offset_0 = tid_1 + 512U * k_0;
        float2 _S47 = float2(0.0f, 0.0f);

#line 1167
        bool _S48;

        if(_S46 < ((&kernelContext_4)->entryPointParams_0->seriesLength_0))
        {

#line 1169
            _S48 = offset_0 < ((&kernelContext_4)->entryPointParams_0->seriesLength_0 - _S46);

#line 1169
        }
        else
        {

#line 1169
            _S48 = false;

#line 1169
        }

#line 1169
        float2 x_2;

#line 1169
        if(_S48)
        {

#line 1169
            x_2 = float2(*((&kernelContext_4)->entryPointParams_series_0+(_S46 + offset_0))) ;

#line 1169
        }
        else
        {

#line 1169
            x_2 = _S47;

#line 1169
        }

        r_5[k_0] = float2(x_2.x / 8192.0f, - x_2.y / 8192.0f);

#line 1165
        k_0 = k_0 + 1U;

#line 1165
    }

#line 1165
    forwardTransform_0(&r_5, tid_1, &kernelContext_4);

#line 1165
    k_0 = 0U;

#line 1174
    for(;;)
    {

#line 1174
        if(k_0 < 16U)
        {
        }
        else
        {

#line 1174
            break;
        }

#line 1174
        *((&kernelContext_4)->entryPointParams_spectra_0+(_S45 * 8192U + slotToIndex_0(tid_1 * 16U + k_0))) = packed_float2(float2(r_5[k_0].x, - r_5[k_0].y)) ;

#line 1174
        k_0 = k_0 + 1U;

#line 1174
    }



    return;
}
