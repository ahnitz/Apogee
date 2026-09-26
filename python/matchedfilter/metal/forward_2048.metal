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


#line 336 "/tmp/tmpkiuf5mcc/forward.slang"
void r4_0(float2 thread* a_0, float2 thread* b_0, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_0 + *c_0;

#line 338
    float2 t1_0 = *a_0 - *c_0;

#line 338
    float2 t2_0 = *b_0 + *d_0;

#line 338
    float2 t3_0 = *b_0 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_0 = t0_0 + t2_0;

#line 340
    *b_0 = t1_0 + j3_0;

#line 340
    *c_0 = t0_0 - t2_0;

#line 340
    *d_0 = t1_0 - j3_0;
    return;
}


#line 186
float2 cmul_0(float2 a_1, float2 b_1)
{

#line 186
    float _S2 = a_1.x;

#line 186
    float _S3 = b_1.x;

#line 186
    float _S4 = a_1.y;

#line 186
    float _S5 = b_1.y;

#line 186
    return float2(_S2 * _S3 - _S4 * _S5, _S2 * _S5 + _S4 * _S3);
}


#line 372
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 379
    uint n1_0 = 0U;
    for(;;)
    {

#line 380
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 380
            break;
        }

#line 380
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 380
        n1_0 = n1_0 + 1U;

#line 380
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 381
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 381
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 382
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 382
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 383
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 383
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 383
    uint k2_0 = 0U;
    for(;;)
    {

#line 384
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 384
            break;
        }

#line 384
        uint _S6 = 4U * k2_0;

#line 384
        r4_0(&(*r_0)[_S6], &(*r_0)[_S6 + 1U], &(*r_0)[_S6 + 2U], &(*r_0)[_S6 + 3U]);

#line 384
        k2_0 = k2_0 + 1U;

#line 384
    }

    float2 t_0 = (*r_0)[int(1)];

#line 386
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 386
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 387
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 387
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 388
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 388
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 389
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 389
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 390
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 390
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 391
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 391
    (*r_0)[int(14)] = t_5;
    return;
}


#line 90 "core"
struct EntryPointParams_0
{
    uint seriesLength_0;
};


#line 175 "/tmp/tmpkiuf5mcc/forward.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_series_0;
    uint device* entryPointParams_starts_0;
    packed_float2 device* entryPointParams_spectra_0;
    uint _tid_0;
    uint _stgBase_0;
    array<uint, int(2048)> threadgroup* stg_0;
};


#line 175
void stgPut_0(uint i_0, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 175
    uint _S7 = 2U * i_0;

#line 175
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S7] = (as_type<uint>((v_0.x)));

#line 175
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S7 + 1U] = (as_type<uint>((v_0.y)));

#line 175
    return;
}


#line 176
float2 stgGet_0(uint i_1, KernelContext_0 thread* kernelContext_1)
{

#line 176
    uint _S8 = 2U * i_1;

#line 176
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S8]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S8 + 1U]))));
}


#line 497
void exchange_0(array<float2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 497
    uint j_0;

#line 508
    thread array<float2, int(16)> out_0;

#line 508
    uint z_0 = 0U;
    for(;;)
    {

#line 509
        if(z_0 < 16U)
        {
        }
        else
        {

#line 509
            break;
        }

#line 509
        out_0[z_0] = float2(0.0f, 0.0f);

#line 509
        z_0 = z_0 + 1U;

#line 509
    }
    uint _S9 = (1U << lgSpan_0) - 1U;
    uint _S10 = (1U << lgLen_0) - 1U;

#line 511
    uint c_1 = 0U;
    for(;;)
    {

#line 512
        if(c_1 < 2U)
        {
        }
        else
        {

#line 512
            break;
        }

#line 513
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 513
        j_0 = 0U;
        for(;;)
        {

#line 514
            if(j_0 < 8U)
            {
            }
            else
            {

#line 514
                break;
            }

#line 514
            stgPut_0(j_0 * 128U + kernelContext_2->_tid_0, (*r_1)[c_1 * 8U + j_0], kernelContext_2);

#line 514
            j_0 = j_0 + 1U;

#line 514
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 515
        uint d_1 = 0U;
        for(;;)
        {

#line 516
            if(d_1 < 16U)
            {
            }
            else
            {

#line 516
                break;
            }
            uint b_2 = ((*want_0)[d_1]) >> lgLen_0;

#line 518
            uint rem_0 = ((*want_0)[d_1]) & _S10;
            uint i_2 = rem_0 >> lgSpan_0;

#line 519
            uint ln_0 = rem_0 & _S9;
            uint _S11 = c_1 * 8U;

#line 520
            bool _S12;

#line 520
            if(i_2 >= _S11)
            {

#line 520
                _S12 = i_2 < ((c_1 + 1U) * 8U);

#line 520
            }
            else
            {

#line 520
                _S12 = false;

#line 520
            }

#line 520
            if(_S12)
            {

#line 520
                float2 _S13 = stgGet_0((i_2 - _S11) * 128U + (b_2 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S13;

#line 520
            }

#line 516
            d_1 = d_1 + 1U;

#line 516
        }

#line 512
        c_1 = c_1 + 1U;

#line 512
    }

#line 512
    j_0 = 0U;

#line 524
    for(;;)
    {

#line 524
        if(j_0 < 16U)
        {
        }
        else
        {

#line 524
            break;
        }

#line 524
        (*r_1)[j_0] = out_0[j_0];

#line 524
        j_0 = j_0 + 1U;

#line 524
    }
    return;
}


#line 356
void dft8_0(array<float2, int(16)> thread* r_2, uint o_0)
{


    thread array<float2, int(8)> b_3;

#line 360
    uint s_0 = 1U;
    for(;;)
    {

#line 361
        if(s_0 < 8U)
        {
        }
        else
        {

#line 361
            break;
        }

#line 361
        uint j_1 = 0U;
        for(;;)
        {

#line 362
            if(j_1 < 4U)
            {
            }
            else
            {

#line 362
                break;
            }

#line 363
            uint k_0 = j_1 & (s_0 - 1U);
            float ang_0 = 3.14159274101257324f * float(k_0) / float(s_0);

            uint _S14 = o_0 + j_1;

#line 366
            float2 t_6 = cmul_0(float2(cos(ang_0), sin(ang_0)), (*r_2)[_S14 + 4U]);
            uint _S15 = ((j_1 - k_0) << 1U) + k_0;

#line 367
            b_3[_S15] = (*r_2)[_S14] + t_6;

#line 367
            b_3[_S15 + s_0] = (*r_2)[_S14] - t_6;

#line 362
            j_1 = j_1 + 1U;

#line 362
        }

#line 362
        uint i_3 = 0U;

#line 369
        for(;;)
        {

#line 369
            if(i_3 < 8U)
            {
            }
            else
            {

#line 369
                break;
            }

#line 369
            (*r_2)[o_0 + i_3] = b_3[i_3];

#line 369
            i_3 = i_3 + 1U;

#line 369
        }

#line 361
        s_0 = s_0 << 1U;

#line 361
    }

#line 371
    return;
}


#line 475
void innermost_0(array<float2, int(16)> thread* r_3)
{

#line 475
    uint b_4 = 0U;

#line 483
    for(;;)
    {

#line 483
        if(b_4 < 2U)
        {
        }
        else
        {

#line 483
            break;
        }

#line 483
        dft8_0(r_3, b_4 * 8U);

#line 483
        b_4 = b_4 + 1U;

#line 483
    }



    return;
}


#line 1155
void forwardTransform_0(array<float2, int(16)> thread* r_4, uint tid_0, KernelContext_0 thread* kernelContext_3)
{

#line 1155
    uint z_1;

#line 1155
    uint _S16;

#line 1155
    uint k2_1;

#line 1155
    float cr_0;

#line 1155
    float ci_0;

#line 1155
    uint _S17;

#line 1155
    uint d_2;

#line 1155
    for(;;)
    {

#line 1155
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



                uint lgTB_0 = firstbithigh_0(128U);

#line 13
                _S16 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(2048U);

                uint lane_0 = tid_0 & 127U;


                dft16_0(r_4);

#line 27
                float a1_0 = 6.28318548202514648f * float(lane_0) / 2048.0f;
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
                uint _S21 = max(128U, 1U);

#line 40
                uint _S22 = 16U / _S21;
                uint _S23 = max(8U, 1U);

#line 41
                _S17 = _S23;
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
                    uint j_2 = d_2 / _S21;

#line 44
                    uint m_0 = d_2 % _S21;
                    want_1[d_2] = _S24 * 128U + _S25 + _S23 * d_2;

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



                uint lgTB_1 = firstbithigh_0(8U);

                uint _S27 = tid_0 >> lgTB_1;
                uint lane_1 = tid_0 & 7U;


                dft16_0(r_4);

#line 27
                float a1_1 = 6.28318548202514648f * float(lane_1) / 128.0f;
                float _S28 = cos(a1_1);

#line 28
                float _S29 = sin(a1_1);

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
                    float nr_1 = cr_0 * _S28 - ci_0 * _S29;
                    float _S30 = cr_0 * _S29 + ci_0 * _S28;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_1;

#line 30
                    ci_0 = _S30;

#line 30
                }

#line 40
                uint _S31 = 16U / _S17;
                uint _S32 = max(0U, 1U);
                uint _S33 = tid_0 / _S32;

#line 42
                uint _S34 = tid_0 % _S32;

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
                    uint m_1 = d_2 % _S17;
                    want_2[d_2] = _S27 * 128U + (lane_1 * _S31 + j_3) * 8U + m_1;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(16)> _S35 = want_2;

#line 43
                exchange_0(r_4, &_S35, _S16, lgTB_1, kernelContext_3);

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

#line 1158 "/tmp/tmpkiuf5mcc/forward.slang"
    return;
}


#line 548
uint lgOf_0(uint i_4)
{

#line 548
    uint _S36;

#line 548
    if(i_4 < 2U)
    {

#line 548
        _S36 = 4U;

#line 548
    }
    else
    {

#line 548
        if(i_4 == 2U)
        {

#line 548
            _S36 = 3U;

#line 548
        }
        else
        {

#line 548
            _S36 = 1U;

#line 548
        }

#line 548
    }

#line 548
    return _S36;
}


#line 550
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(2U);

    uint x_0 = slot_0 >> lg_0;

#line 554
    uint lg_1 = lgOf_0(1U);

#line 554
    uint lg_2 = lgOf_0(0U);

#line 559
    return (((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | ((x_0 >> lg_1) & ((1U << lg_2) - 1U));
}


#line 1163
[[kernel]] void seriesForward(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_series_1 [[buffer(1)]], uint device* entryPointParams_starts_1 [[buffer(2)]], packed_float2 device* entryPointParams_spectra_1 [[buffer(3)]])
{

#line 1163
    thread KernelContext_0 kernelContext_4;

#line 1163
    (&kernelContext_4)->entryPointParams_0 = entryPointParams_1;

#line 1163
    (&kernelContext_4)->entryPointParams_series_0 = entryPointParams_series_1;

#line 1163
    (&kernelContext_4)->entryPointParams_starts_0 = entryPointParams_starts_1;

#line 1163
    (&kernelContext_4)->entryPointParams_spectra_0 = entryPointParams_spectra_1;

#line 1163
    threadgroup array<uint, int(2048)> stg_1;

#line 1163
    (&kernelContext_4)->stg_0 = &stg_1;

#line 1169
    uint tid_1 = lid_0.x;
    (&kernelContext_4)->_tid_0 = tid_1;
    (&kernelContext_4)->_stgBase_0 = 0U;
    uint _S37 = gid_0.x;

#line 1172
    uint _S38 = entryPointParams_starts_1[_S37];
    thread array<float2, int(16)> r_5;

#line 1173
    uint k_1 = 0U;
    for(;;)
    {

#line 1174
        if(k_1 < 16U)
        {
        }
        else
        {

#line 1174
            break;
        }

#line 1175
        uint offset_0 = tid_1 + 128U * k_1;
        float2 _S39 = float2(0.0f, 0.0f);

#line 1176
        bool _S40;

        if(_S38 < ((&kernelContext_4)->entryPointParams_0->seriesLength_0))
        {

#line 1178
            _S40 = offset_0 < ((&kernelContext_4)->entryPointParams_0->seriesLength_0 - _S38);

#line 1178
        }
        else
        {

#line 1178
            _S40 = false;

#line 1178
        }

#line 1178
        float2 x_1;

#line 1178
        if(_S40)
        {

#line 1178
            x_1 = float2(*((&kernelContext_4)->entryPointParams_series_0+(_S38 + offset_0))) ;

#line 1178
        }
        else
        {

#line 1178
            x_1 = _S39;

#line 1178
        }

        r_5[k_1] = float2(x_1.x / 2048.0f, - x_1.y / 2048.0f);

#line 1174
        k_1 = k_1 + 1U;

#line 1174
    }

#line 1174
    forwardTransform_0(&r_5, tid_1, &kernelContext_4);

#line 1174
    k_1 = 0U;

#line 1183
    for(;;)
    {

#line 1183
        if(k_1 < 16U)
        {
        }
        else
        {

#line 1183
            break;
        }

#line 1183
        *((&kernelContext_4)->entryPointParams_spectra_0+(_S37 * 2048U + slotToIndex_0(tid_1 * 16U + k_1))) = packed_float2(float2(r_5[k_1].x, - r_5[k_1].y)) ;

#line 1183
        k_1 = k_1 + 1U;

#line 1183
    }



    return;
}
