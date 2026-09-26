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


#line 333 "/tmp/tmpy6ru_r3k/forward.slang"
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


#line 435
void dft64_0(array<float2, int(64)> thread* r_1)
{

#line 435
    uint k_0;

#line 435
    uint j_0 = 0U;

    for(;;)
    {

#line 437
        if(j_0 < 16U)
        {
        }
        else
        {

#line 437
            break;
        }

#line 438
        r4_0(&(*r_1)[j_0], &(*r_1)[j_0 + 16U], &(*r_1)[j_0 + 32U], &(*r_1)[j_0 + 48U]);

#line 437
        j_0 = j_0 + 1U;

#line 437
    }

    thread array<float2, int(64)> o_0;

#line 439
    uint pp_0 = 0U;
    for(;;)
    {

#line 440
        if(pp_0 < 4U)
        {
        }
        else
        {

#line 440
            break;
        }

#line 441
        thread array<float2, int(16)> b_2;

#line 441
        j_0 = 0U;
        for(;;)
        {

#line 442
            if(j_0 < 16U)
            {
            }
            else
            {

#line 442
                break;
            }

#line 443
            float ang_0 = 6.28318548202514648f * float(pp_0 * j_0) / 64.0f;
            b_2[j_0] = cmul_0((*r_1)[pp_0 * 16U + j_0], float2(cos(ang_0), sin(ang_0)));

#line 442
            j_0 = j_0 + 1U;

#line 442
        }



        dft16_0(&b_2);

#line 446
        k_0 = 0U;
        for(;;)
        {

#line 447
            if(k_0 < 16U)
            {
            }
            else
            {

#line 447
                break;
            }

#line 447
            o_0[4U * k_0 + pp_0] = b_2[k_0];

#line 447
            k_0 = k_0 + 1U;

#line 447
        }

#line 440
        pp_0 = pp_0 + 1U;

#line 440
    }

#line 440
    k_0 = 0U;

#line 449
    for(;;)
    {

#line 449
        if(k_0 < 64U)
        {
        }
        else
        {

#line 449
            break;
        }

#line 449
        (*r_1)[k_0] = o_0[k_0];

#line 449
        k_0 = k_0 + 1U;

#line 449
    }
    return;
}


void dftR_0(array<float2, int(64)> thread* r_2)
{

#line 461
    dft64_0(r_2);

    return;
}


#line 90 "core"
struct EntryPointParams_0
{
    uint seriesLength_0;
};


#line 172 "/tmp/tmpy6ru_r3k/forward.slang"
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
void exchange_0(array<float2, int(64)> thread* r_3, const array<uint, int(64)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 494
    uint j_1;

#line 505
    thread array<float2, int(64)> out_0;

#line 505
    uint z_0 = 0U;
    for(;;)
    {

#line 506
        if(z_0 < 64U)
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
        if(c_1 < 16U)
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
            if(d_1 < 64U)
            {
            }
            else
            {

#line 513
                break;
            }
            uint b_3 = ((*want_0)[d_1]) >> lgLen_0;

#line 515
            uint rem_0 = ((*want_0)[d_1]) & _S10;
            uint i_2 = rem_0 >> lgSpan_0;

#line 516
            uint ln_0 = rem_0 & _S9;
            uint _S11 = c_1 * 4U;

#line 517
            bool _S12;

#line 517
            if(i_2 >= _S11)
            {

#line 517
                _S12 = i_2 < ((c_1 + 1U) * 4U);

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
                float2 _S13 = stgGet_0((i_2 - _S11) * 1024U + (b_3 << lgSpan_0) + ln_0, kernelContext_2);
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
    j_1 = 0U;

#line 521
    for(;;)
    {

#line 521
        if(j_1 < 64U)
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


#line 394
void dft16at_0(array<float2, int(64)> thread* r_4, uint o_1)
{



    thread array<float2, int(16)> b_4;

#line 399
    uint i_3 = 0U;
    for(;;)
    {

#line 400
        if(i_3 < 16U)
        {
        }
        else
        {

#line 400
            break;
        }

#line 400
        b_4[i_3] = (*r_4)[o_1 + i_3];

#line 400
        i_3 = i_3 + 1U;

#line 400
    }
    dft16_0(&b_4);

#line 401
    i_3 = 0U;
    for(;;)
    {

#line 402
        if(i_3 < 16U)
        {
        }
        else
        {

#line 402
            break;
        }

#line 402
        (*r_4)[o_1 + i_3] = b_4[i_3];

#line 402
        i_3 = i_3 + 1U;

#line 402
    }

    return;
}


#line 472
void innermost_0(array<float2, int(64)> thread* r_5)
{

#line 472
    uint b_5 = 0U;

#line 477
    for(;;)
    {

#line 477
        if(b_5 < 4U)
        {
        }
        else
        {

#line 477
            break;
        }

#line 477
        dft16at_0(r_5, b_5 * 16U);

#line 477
        b_5 = b_5 + 1U;

#line 477
    }

#line 484
    return;
}


#line 1104
void forwardTransform_0(array<float2, int(64)> thread* r_6, uint tid_0, KernelContext_0 thread* kernelContext_3)
{

#line 1104
    uint z_1;

#line 1104
    uint _S14;

#line 1104
    uint k2_1;

#line 1104
    float cr_0;

#line 1104
    float ci_0;

#line 1104
    uint _S15;

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
                thread array<uint, int(64)> want_1;

#line 7
                z_1 = 0U;
                for(;;)
                {

#line 8
                    if(z_1 < 64U)
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
                _S14 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(65536U);

                uint lane_0 = tid_0 & 1023U;

#line 20
                dftR_0(r_6);

#line 26
                float a1_0 = 6.28318548202514648f * float(lane_0) / 6.5536e+04f;
                float _S16 = cos(a1_0);

#line 27
                float _S17 = sin(a1_0);

#line 27
                k2_1 = 0U;

#line 27
                cr_0 = 1.0f;

#line 27
                ci_0 = 0.0f;

                for(;;)
                {

#line 29
                    if(k2_1 < 64U)
                    {
                    }
                    else
                    {

#line 29
                        break;
                    }

#line 30
                    (*r_6)[k2_1] = cmul_0((*r_6)[k2_1], float2(cr_0, ci_0));
                    float nr_0 = cr_0 * _S16 - ci_0 * _S17;
                    float _S18 = cr_0 * _S17 + ci_0 * _S16;

#line 29
                    k2_1 = k2_1 + 1U;

#line 29
                    cr_0 = nr_0;

#line 29
                    ci_0 = _S18;

#line 29
                }

#line 39
                uint _S19 = max(1024U, 1U);

#line 39
                uint _S20 = 64U / _S19;
                uint _S21 = max(16U, 1U);

#line 40
                _S15 = _S21;
                uint _S22 = tid_0 / _S21;

#line 41
                uint _S23 = tid_0 % _S21;

#line 41
                d_2 = 0U;
                for(;;)
                {

#line 42
                    if(d_2 < 64U)
                    {
                    }
                    else
                    {

#line 42
                        break;
                    }

#line 43
                    uint j_2 = d_2 / _S19;

#line 43
                    uint m_0 = d_2 % _S19;
                    want_1[d_2] = _S22 * 1024U + _S23 + _S21 * d_2;

#line 42
                    d_2 = d_2 + 1U;

#line 42
                }

#line 42
                thread array<uint, int(64)> _S24 = want_1;

#line 42
                exchange_0(r_6, &_S24, lgLn_0, lgTB_0, kernelContext_3);

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
                thread array<uint, int(64)> want_2;

#line 7
                z_1 = 0U;
                for(;;)
                {

#line 8
                    if(z_1 < 64U)
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



                uint lgTB_1 = firstbithigh_0(16U);

                uint _S25 = tid_0 >> lgTB_1;
                uint lane_1 = tid_0 & 15U;

#line 20
                dftR_0(r_6);

#line 26
                float a1_1 = 6.28318548202514648f * float(lane_1) / 1024.0f;
                float _S26 = cos(a1_1);

#line 27
                float _S27 = sin(a1_1);

#line 27
                k2_1 = 0U;

#line 27
                cr_0 = 1.0f;

#line 27
                ci_0 = 0.0f;

                for(;;)
                {

#line 29
                    if(k2_1 < 64U)
                    {
                    }
                    else
                    {

#line 29
                        break;
                    }

#line 30
                    (*r_6)[k2_1] = cmul_0((*r_6)[k2_1], float2(cr_0, ci_0));
                    float nr_1 = cr_0 * _S26 - ci_0 * _S27;
                    float _S28 = cr_0 * _S27 + ci_0 * _S26;

#line 29
                    k2_1 = k2_1 + 1U;

#line 29
                    cr_0 = nr_1;

#line 29
                    ci_0 = _S28;

#line 29
                }

#line 39
                uint _S29 = 64U / _S15;
                uint _S30 = max(0U, 1U);
                uint _S31 = tid_0 / _S30;

#line 41
                uint _S32 = tid_0 % _S30;

#line 41
                d_2 = 0U;
                for(;;)
                {

#line 42
                    if(d_2 < 64U)
                    {
                    }
                    else
                    {

#line 42
                        break;
                    }

#line 43
                    uint j_3 = d_2 / _S15;

#line 43
                    uint m_1 = d_2 % _S15;
                    want_2[d_2] = _S25 * 1024U + (lane_1 * _S29 + j_3) * 16U + m_1;

#line 42
                    d_2 = d_2 + 1U;

#line 42
                }

#line 42
                thread array<uint, int(64)> _S33 = want_2;

#line 42
                exchange_0(r_6, &_S33, _S14, lgTB_1, kernelContext_3);

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
    innermost_0(r_6);

#line 1107 "/tmp/tmpy6ru_r3k/forward.slang"
    return;
}


#line 545
uint lgOf_0(uint i_4)
{

#line 545
    uint _S34;

#line 545
    if(i_4 < 2U)
    {

#line 545
        _S34 = 6U;

#line 545
    }
    else
    {

#line 545
        if(i_4 == 2U)
        {

#line 545
            _S34 = 4U;

#line 545
        }
        else
        {

#line 545
            _S34 = 1U;

#line 545
        }

#line 545
    }

#line 545
    return _S34;
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
    uint _S35 = gid_0.x;

#line 1121
    uint _S36 = entryPointParams_starts_1[_S35];
    thread array<float2, int(64)> r_7;

#line 1122
    uint k_1 = 0U;
    for(;;)
    {

#line 1123
        if(k_1 < 64U)
        {
        }
        else
        {

#line 1123
            break;
        }

#line 1124
        uint offset_0 = tid_1 + 1024U * k_1;
        float2 _S37 = float2(0.0f, 0.0f);

#line 1125
        bool _S38;

        if(_S36 < ((&kernelContext_4)->entryPointParams_0->seriesLength_0))
        {

#line 1127
            _S38 = offset_0 < ((&kernelContext_4)->entryPointParams_0->seriesLength_0 - _S36);

#line 1127
        }
        else
        {

#line 1127
            _S38 = false;

#line 1127
        }

#line 1127
        float2 x_1;

#line 1127
        if(_S38)
        {

#line 1127
            x_1 = float2(*((&kernelContext_4)->entryPointParams_series_0+(_S36 + offset_0))) ;

#line 1127
        }
        else
        {

#line 1127
            x_1 = _S37;

#line 1127
        }

        r_7[k_1] = float2(x_1.x / 6.5536e+04f, - x_1.y / 6.5536e+04f);

#line 1123
        k_1 = k_1 + 1U;

#line 1123
    }

#line 1123
    forwardTransform_0(&r_7, tid_1, &kernelContext_4);

#line 1123
    k_1 = 0U;

#line 1132
    for(;;)
    {

#line 1132
        if(k_1 < 64U)
        {
        }
        else
        {

#line 1132
            break;
        }

#line 1132
        *((&kernelContext_4)->entryPointParams_spectra_0+(_S35 * 65536U + slotToIndex_0(tid_1 * 64U + k_1))) = packed_float2(float2(r_7[k_1].x, - r_7[k_1].y)) ;

#line 1132
        k_1 = k_1 + 1U;

#line 1132
    }



    return;
}
