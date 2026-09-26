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


#line 183 "/tmp/tmp2eaeij6h/forward.slang"
float2 cmul_0(float2 a_0, float2 b_0)
{

#line 183
    float _S2 = a_0.x;

#line 183
    float _S3 = b_0.x;

#line 183
    float _S4 = a_0.y;

#line 183
    float _S5 = b_0.y;

#line 183
    return float2(_S2 * _S3 - _S4 * _S5, _S2 * _S5 + _S4 * _S3);
}


#line 333
void r4_0(float2 thread* a_1, float2 thread* b_1, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_1 + *c_0;

#line 335
    float2 t1_0 = *a_1 - *c_0;

#line 335
    float2 t2_0 = *b_1 + *d_0;

#line 335
    float2 t3_0 = *b_1 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_1 = t0_0 + t2_0;

#line 337
    *b_1 = t1_0 + j3_0;

#line 337
    *c_0 = t0_0 - t2_0;

#line 337
    *d_0 = t1_0 - j3_0;
    return;
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


#line 415
void dft32_0(array<float2, int(32)> thread* r_1)
{
    thread array<float2, int(16)> u_0;

#line 417
    thread array<float2, int(16)> v_0;

#line 417
    uint j_0 = 0U;
    for(;;)
    {

#line 418
        if(j_0 < 16U)
        {
        }
        else
        {

#line 418
            break;
        }
        u_0[j_0] = (*r_1)[j_0] + (*r_1)[j_0 + 16U];
        float ang_0 = 6.28318548202514648f * float(j_0) / 32.0f;
        v_0[j_0] = cmul_0((*r_1)[j_0] - (*r_1)[j_0 + 16U], float2(cos(ang_0), sin(ang_0)));

#line 418
        j_0 = j_0 + 1U;

#line 418
    }

#line 424
    dft16_0(&u_0);
    dft16_0(&v_0);

#line 425
    uint k_0 = 0U;
    for(;;)
    {

#line 426
        if(k_0 < 16U)
        {
        }
        else
        {

#line 426
            break;
        }

#line 426
        uint _S7 = 2U * k_0;

#line 426
        (*r_1)[_S7] = u_0[k_0];

#line 426
        (*r_1)[_S7 + 1U] = v_0[k_0];

#line 426
        k_0 = k_0 + 1U;

#line 426
    }
    return;
}


#line 454
void dftR_0(array<float2, int(32)> thread* r_2)
{



    dft32_0(r_2);



    return;
}


#line 90 "core"
struct EntryPointParams_0
{
    uint seriesLength_0;
};


#line 172 "/tmp/tmp2eaeij6h/forward.slang"
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
void stgPut_0(uint i_0, float2 v_1, KernelContext_0 thread* kernelContext_0)
{

#line 172
    uint _S8 = 2U * i_0;

#line 172
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S8] = (as_type<uint>((v_1.x)));

#line 172
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S8 + 1U] = (as_type<uint>((v_1.y)));

#line 172
    return;
}


#line 173
float2 stgGet_0(uint i_1, KernelContext_0 thread* kernelContext_1)
{

#line 173
    uint _S9 = 2U * i_1;

#line 173
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S9]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S9 + 1U]))));
}


#line 494
void exchange_0(array<float2, int(32)> thread* r_3, const array<uint, int(32)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 494
    uint j_1;

#line 505
    thread array<float2, int(32)> out_0;

#line 505
    uint z_0 = 0U;
    for(;;)
    {

#line 506
        if(z_0 < 32U)
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
    uint _S10 = (1U << lgSpan_0) - 1U;
    uint _S11 = (1U << lgLen_0) - 1U;

#line 508
    uint c_1 = 0U;
    for(;;)
    {

#line 509
        if(c_1 < 8U)
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
        j_1 = 0U;
        for(;;)
        {

#line 511
            if(j_1 < 4U)
            {
            }
            else
            {

#line 511
                break;
            }

#line 511
            stgPut_0(j_1 * 1024U + kernelContext_2->_tid_0, (*r_3)[c_1 * 4U + j_1], kernelContext_2);

#line 511
            j_1 = j_1 + 1U;

#line 511
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 512
        uint d_1 = 0U;
        for(;;)
        {

#line 513
            if(d_1 < 32U)
            {
            }
            else
            {

#line 513
                break;
            }
            uint b_2 = ((*want_0)[d_1]) >> lgLen_0;

#line 515
            uint rem_0 = ((*want_0)[d_1]) & _S11;
            uint i_2 = rem_0 >> lgSpan_0;

#line 516
            uint ln_0 = rem_0 & _S10;
            uint _S12 = c_1 * 4U;

#line 517
            bool _S13;

#line 517
            if(i_2 >= _S12)
            {

#line 517
                _S13 = i_2 < ((c_1 + 1U) * 4U);

#line 517
            }
            else
            {

#line 517
                _S13 = false;

#line 517
            }

#line 517
            if(_S13)
            {

#line 517
                float2 _S14 = stgGet_0((i_2 - _S12) * 1024U + (b_2 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S14;

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
    j_1 = 0U;

#line 521
    for(;;)
    {

#line 521
        if(j_1 < 32U)
        {
        }
        else
        {

#line 521
            break;
        }

#line 521
        (*r_3)[j_1] = out_0[j_1];

#line 521
        j_1 = j_1 + 1U;

#line 521
    }
    return;
}


#line 472
void innermost_0(array<float2, int(32)> thread* r_4)
{

    dft32_0(r_4);

#line 484
    return;
}


#line 1104
void forwardTransform_0(array<float2, int(32)> thread* r_5, uint tid_0, KernelContext_0 thread* kernelContext_3)
{

#line 1104
    uint z_1;

#line 1104
    uint _S15;

#line 1104
    uint k2_1;

#line 1104
    float cr_0;

#line 1104
    float ci_0;

#line 1104
    uint _S16;

#line 1104
    uint d_2;

#line 1104
    for(;;)
    {

#line 1104
        for(;;)
        {

#line 6 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/src/gpu/fft_transform.slang"
            for(;;)
            {

#line 7
                thread array<uint, int(32)> want_1;

#line 7
                z_1 = 0U;
                for(;;)
                {

#line 8
                    if(z_1 < 32U)
                    {
                    }
                    else
                    {

#line 8
                        break;
                    }

#line 8
                    want_1[z_1] = 0U;

#line 8
                    z_1 = z_1 + 1U;

#line 8
                }



                uint lgTB_0 = firstbithigh_0(1024U);

#line 12
                _S15 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(32768U);

                uint lane_0 = tid_0 & 1023U;

#line 20
                dftR_0(r_5);

#line 26
                float a1_0 = 6.28318548202514648f * float(lane_0) / 32768.0f;
                float _S17 = cos(a1_0);

#line 27
                float _S18 = sin(a1_0);

#line 27
                k2_1 = 0U;

#line 27
                cr_0 = 1.0f;

#line 27
                ci_0 = 0.0f;

                for(;;)
                {

#line 29
                    if(k2_1 < 32U)
                    {
                    }
                    else
                    {

#line 29
                        break;
                    }

#line 30
                    (*r_5)[k2_1] = cmul_0((*r_5)[k2_1], float2(cr_0, ci_0));
                    float nr_0 = cr_0 * _S17 - ci_0 * _S18;
                    float _S19 = cr_0 * _S18 + ci_0 * _S17;

#line 29
                    k2_1 = k2_1 + 1U;

#line 29
                    cr_0 = nr_0;

#line 29
                    ci_0 = _S19;

#line 29
                }

#line 39
                uint _S20 = max(1024U, 1U);

#line 39
                uint _S21 = 32U / _S20;
                uint _S22 = max(32U, 1U);

#line 40
                _S16 = _S22;
                uint _S23 = tid_0 / _S22;

#line 41
                uint _S24 = tid_0 % _S22;

#line 41
                d_2 = 0U;
                for(;;)
                {

#line 42
                    if(d_2 < 32U)
                    {
                    }
                    else
                    {

#line 42
                        break;
                    }

#line 43
                    uint j_2 = d_2 / _S20;

#line 43
                    uint m_0 = d_2 % _S20;
                    want_1[d_2] = _S23 * 1024U + _S24 + _S22 * d_2;

#line 42
                    d_2 = d_2 + 1U;

#line 42
                }

#line 42
                thread array<uint, int(32)> _S25 = want_1;

#line 42
                exchange_0(r_5, &_S25, lgLn_0, lgTB_0, kernelContext_3);

#line 6
                break;
            }

#line 6
            break;
        }

#line 6
        for(;;)
        {

#line 6
            for(;;)
            {

#line 7
                thread array<uint, int(32)> want_2;

#line 7
                z_1 = 0U;
                for(;;)
                {

#line 8
                    if(z_1 < 32U)
                    {
                    }
                    else
                    {

#line 8
                        break;
                    }

#line 8
                    want_2[z_1] = 0U;

#line 8
                    z_1 = z_1 + 1U;

#line 8
                }



                uint lgTB_1 = firstbithigh_0(32U);

                uint _S26 = tid_0 >> lgTB_1;
                uint lane_1 = tid_0 & 31U;

#line 20
                dftR_0(r_5);

#line 26
                float a1_1 = 6.28318548202514648f * float(lane_1) / 1024.0f;
                float _S27 = cos(a1_1);

#line 27
                float _S28 = sin(a1_1);

#line 27
                k2_1 = 0U;

#line 27
                cr_0 = 1.0f;

#line 27
                ci_0 = 0.0f;

                for(;;)
                {

#line 29
                    if(k2_1 < 32U)
                    {
                    }
                    else
                    {

#line 29
                        break;
                    }

#line 30
                    (*r_5)[k2_1] = cmul_0((*r_5)[k2_1], float2(cr_0, ci_0));
                    float nr_1 = cr_0 * _S27 - ci_0 * _S28;
                    float _S29 = cr_0 * _S28 + ci_0 * _S27;

#line 29
                    k2_1 = k2_1 + 1U;

#line 29
                    cr_0 = nr_1;

#line 29
                    ci_0 = _S29;

#line 29
                }

#line 39
                uint _S30 = 32U / _S16;
                uint _S31 = max(1U, 1U);
                uint _S32 = tid_0 / _S31;

#line 41
                uint _S33 = tid_0 % _S31;

#line 41
                d_2 = 0U;
                for(;;)
                {

#line 42
                    if(d_2 < 32U)
                    {
                    }
                    else
                    {

#line 42
                        break;
                    }

#line 43
                    uint j_3 = d_2 / _S16;

#line 43
                    uint m_1 = d_2 % _S16;
                    want_2[d_2] = _S26 * 1024U + (lane_1 * _S30 + j_3) * 32U + m_1;

#line 42
                    d_2 = d_2 + 1U;

#line 42
                }

#line 42
                thread array<uint, int(32)> _S34 = want_2;

#line 42
                exchange_0(r_5, &_S34, _S15, lgTB_1, kernelContext_3);

#line 6
                break;
            }

#line 6
            break;
        }

#line 6
        break;
    }

#line 50
    innermost_0(r_5);

#line 1107 "/tmp/tmp2eaeij6h/forward.slang"
    return;
}


#line 545
uint lgOf_0(uint i_3)
{

#line 545
    uint _S35;

#line 545
    if(i_3 < 2U)
    {

#line 545
        _S35 = 5U;

#line 545
    }
    else
    {

#line 545
        if(i_3 == 2U)
        {

#line 545
            _S35 = 5U;

#line 545
        }
        else
        {

#line 545
            _S35 = 1U;

#line 545
        }

#line 545
    }

#line 545
    return _S35;
}


#line 547
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(2U);

    uint x_0 = slot_0 >> lg_0;

#line 551
    uint lg_1 = lgOf_0(1U);

#line 551
    uint lg_2 = lgOf_0(0U);

#line 556
    return (((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | ((x_0 >> lg_1) & ((1U << lg_2) - 1U));
}


#line 1112
[[kernel]] void seriesForward(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_series_1 [[buffer(1)]], uint device* entryPointParams_starts_1 [[buffer(2)]], packed_float2 device* entryPointParams_spectra_1 [[buffer(3)]])
{

#line 1112
    thread KernelContext_0 kernelContext_4;

#line 1112
    (&kernelContext_4)->entryPointParams_0 = entryPointParams_1;

#line 1112
    (&kernelContext_4)->entryPointParams_series_0 = entryPointParams_series_1;

#line 1112
    (&kernelContext_4)->entryPointParams_starts_0 = entryPointParams_starts_1;

#line 1112
    (&kernelContext_4)->entryPointParams_spectra_0 = entryPointParams_spectra_1;

#line 1112
    threadgroup array<uint, int(8192)> stg_1;

#line 1112
    (&kernelContext_4)->stg_0 = &stg_1;

#line 1118
    uint tid_1 = lid_0.x;
    (&kernelContext_4)->_tid_0 = tid_1;
    (&kernelContext_4)->_stgBase_0 = 0U;
    uint _S36 = gid_0.x;

#line 1121
    uint _S37 = entryPointParams_starts_1[_S36];
    thread array<float2, int(32)> r_6;

#line 1122
    uint k_1 = 0U;
    for(;;)
    {

#line 1123
        if(k_1 < 32U)
        {
        }
        else
        {

#line 1123
            break;
        }

#line 1124
        uint offset_0 = tid_1 + 1024U * k_1;
        float2 _S38 = float2(0.0f, 0.0f);

#line 1125
        bool _S39;

        if(_S37 < ((&kernelContext_4)->entryPointParams_0->seriesLength_0))
        {

#line 1127
            _S39 = offset_0 < ((&kernelContext_4)->entryPointParams_0->seriesLength_0 - _S37);

#line 1127
        }
        else
        {

#line 1127
            _S39 = false;

#line 1127
        }

#line 1127
        float2 x_1;

#line 1127
        if(_S39)
        {

#line 1127
            x_1 = float2(*((&kernelContext_4)->entryPointParams_series_0+(_S37 + offset_0))) ;

#line 1127
        }
        else
        {

#line 1127
            x_1 = _S38;

#line 1127
        }

        r_6[k_1] = float2(x_1.x / 32768.0f, - x_1.y / 32768.0f);

#line 1123
        k_1 = k_1 + 1U;

#line 1123
    }

#line 1123
    forwardTransform_0(&r_6, tid_1, &kernelContext_4);

#line 1123
    k_1 = 0U;

#line 1132
    for(;;)
    {

#line 1132
        if(k_1 < 32U)
        {
        }
        else
        {

#line 1132
            break;
        }

#line 1132
        *((&kernelContext_4)->entryPointParams_spectra_0+(_S36 * 32768U + slotToIndex_0(tid_1 * 32U + k_1))) = packed_float2(float2(r_6[k_1].x, - r_6[k_1].y)) ;

#line 1132
        k_1 = k_1 + 1U;

#line 1132
    }



    return;
}
