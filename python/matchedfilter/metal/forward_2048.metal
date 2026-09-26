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


#line 304 "/tmp/tmp7pah8ipj/forward.slang"
void r4_0(float2 thread* a_0, float2 thread* b_0, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_0 + *c_0;

#line 306
    float2 t1_0 = *a_0 - *c_0;

#line 306
    float2 t2_0 = *b_0 + *d_0;

#line 306
    float2 t3_0 = *b_0 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_0 = t0_0 + t2_0;

#line 308
    *b_0 = t1_0 + j3_0;

#line 308
    *c_0 = t0_0 - t2_0;

#line 308
    *d_0 = t1_0 - j3_0;
    return;
}


#line 154
float2 cmul_0(float2 a_1, float2 b_1)
{

#line 154
    float _S2 = a_1.x;

#line 154
    float _S3 = b_1.x;

#line 154
    float _S4 = a_1.y;

#line 154
    float _S5 = b_1.y;

#line 154
    return float2(_S2 * _S3 - _S4 * _S5, _S2 * _S5 + _S4 * _S3);
}


#line 340
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 347
    uint n1_0 = 0U;
    for(;;)
    {

#line 348
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 348
            break;
        }

#line 348
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 348
        n1_0 = n1_0 + 1U;

#line 348
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 349
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 349
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 350
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 350
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 351
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 351
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 351
    uint k2_0 = 0U;
    for(;;)
    {

#line 352
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 352
            break;
        }

#line 352
        uint _S6 = 4U * k2_0;

#line 352
        r4_0(&(*r_0)[_S6], &(*r_0)[_S6 + 1U], &(*r_0)[_S6 + 2U], &(*r_0)[_S6 + 3U]);

#line 352
        k2_0 = k2_0 + 1U;

#line 352
    }

    float2 t_0 = (*r_0)[int(1)];

#line 354
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 354
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 355
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 355
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 356
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 356
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 357
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 357
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 358
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 358
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 359
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 359
    (*r_0)[int(14)] = t_5;
    return;
}


#line 90 "core"
struct EntryPointParams_0
{
    uint seriesLength_0;
};


#line 143 "/tmp/tmp7pah8ipj/forward.slang"
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


#line 143
void stgPut_0(uint i_0, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 143
    uint _S7 = 2U * i_0;

#line 143
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S7] = (as_type<uint>((v_0.x)));

#line 143
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S7 + 1U] = (as_type<uint>((v_0.y)));

#line 143
    return;
}


#line 144
float2 stgGet_0(uint i_1, KernelContext_0 thread* kernelContext_1)
{

#line 144
    uint _S8 = 2U * i_1;

#line 144
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S8]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S8 + 1U]))));
}


#line 381
void exchange_0(array<float2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 381
    uint j_0;

#line 392
    thread array<float2, int(16)> out_0;

#line 392
    uint z_0 = 0U;
    for(;;)
    {

#line 393
        if(z_0 < 16U)
        {
        }
        else
        {

#line 393
            break;
        }

#line 393
        out_0[z_0] = float2(0.0f, 0.0f);

#line 393
        z_0 = z_0 + 1U;

#line 393
    }
    uint _S9 = (1U << lgSpan_0) - 1U;
    uint _S10 = (1U << lgLen_0) - 1U;

#line 395
    uint c_1 = 0U;
    for(;;)
    {

#line 396
        if(c_1 < 2U)
        {
        }
        else
        {

#line 396
            break;
        }

#line 397
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 397
        j_0 = 0U;
        for(;;)
        {

#line 398
            if(j_0 < 8U)
            {
            }
            else
            {

#line 398
                break;
            }

#line 398
            stgPut_0(j_0 * 128U + kernelContext_2->_tid_0, (*r_1)[c_1 * 8U + j_0], kernelContext_2);

#line 398
            j_0 = j_0 + 1U;

#line 398
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 399
        uint d_1 = 0U;
        for(;;)
        {

#line 400
            if(d_1 < 16U)
            {
            }
            else
            {

#line 400
                break;
            }
            uint b_2 = ((*want_0)[d_1]) >> lgLen_0;

#line 402
            uint rem_0 = ((*want_0)[d_1]) & _S10;
            uint i_2 = rem_0 >> lgSpan_0;

#line 403
            uint ln_0 = rem_0 & _S9;
            uint _S11 = c_1 * 8U;

#line 404
            bool _S12;

#line 404
            if(i_2 >= _S11)
            {

#line 404
                _S12 = i_2 < ((c_1 + 1U) * 8U);

#line 404
            }
            else
            {

#line 404
                _S12 = false;

#line 404
            }

#line 404
            if(_S12)
            {

#line 404
                float2 _S13 = stgGet_0((i_2 - _S11) * 128U + (b_2 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S13;

#line 404
            }

#line 400
            d_1 = d_1 + 1U;

#line 400
        }

#line 396
        c_1 = c_1 + 1U;

#line 396
    }

#line 396
    j_0 = 0U;

#line 408
    for(;;)
    {

#line 408
        if(j_0 < 16U)
        {
        }
        else
        {

#line 408
            break;
        }

#line 408
        (*r_1)[j_0] = out_0[j_0];

#line 408
        j_0 = j_0 + 1U;

#line 408
    }
    return;
}


#line 324
void dft8_0(array<float2, int(16)> thread* r_2, uint o_0)
{


    thread array<float2, int(8)> b_3;

#line 328
    uint s_0 = 1U;
    for(;;)
    {

#line 329
        if(s_0 < 8U)
        {
        }
        else
        {

#line 329
            break;
        }

#line 329
        uint j_1 = 0U;
        for(;;)
        {

#line 330
            if(j_1 < 4U)
            {
            }
            else
            {

#line 330
                break;
            }

#line 331
            uint k_0 = j_1 & (s_0 - 1U);
            float ang_0 = 3.14159274101257324f * float(k_0) / float(s_0);

            uint _S14 = o_0 + j_1;

#line 334
            float2 t_6 = cmul_0(float2(cos(ang_0), sin(ang_0)), (*r_2)[_S14 + 4U]);
            uint _S15 = ((j_1 - k_0) << 1U) + k_0;

#line 335
            b_3[_S15] = (*r_2)[_S14] + t_6;

#line 335
            b_3[_S15 + s_0] = (*r_2)[_S14] - t_6;

#line 330
            j_1 = j_1 + 1U;

#line 330
        }

#line 330
        uint i_3 = 0U;

#line 337
        for(;;)
        {

#line 337
            if(i_3 < 8U)
            {
            }
            else
            {

#line 337
                break;
            }

#line 337
            (*r_2)[o_0 + i_3] = b_3[i_3];

#line 337
            i_3 = i_3 + 1U;

#line 337
        }

#line 329
        s_0 = s_0 << 1U;

#line 329
    }

#line 339
    return;
}


#line 365
void innermost_0(array<float2, int(16)> thread* r_3)
{

#line 365
    uint b_4 = 0U;


    for(;;)
    {

#line 368
        if(b_4 < 2U)
        {
        }
        else
        {

#line 368
            break;
        }

#line 368
        dft8_0(r_3, b_4 * 8U);

#line 368
        b_4 = b_4 + 1U;

#line 368
    }


    return;
}


#line 861
void forwardTransform_0(array<float2, int(16)> thread* r_4, uint tid_0, KernelContext_0 thread* kernelContext_3)
{

#line 861
    uint z_1;

#line 861
    uint _S16;

#line 861
    uint k2_1;

#line 861
    float cr_0;

#line 861
    float ci_0;

#line 861
    uint _S17;

#line 861
    uint d_2;

#line 861
    for(;;)
    {

#line 861
        for(;;)
        {

#line 6 "/tmp/mf-forward-review/src/gpu/fft_transform.slang"
            for(;;)
            {

#line 7
                thread array<uint, int(16)> want_1;

#line 7
                z_1 = 0U;
                for(;;)
                {

#line 8
                    if(z_1 < 16U)
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



                uint lgTB_0 = firstbithigh_0(128U);

#line 12
                _S16 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(2048U);

                uint lane_0 = tid_0 & 127U;


                dft16_0(r_4);

#line 26
                float a1_0 = 6.28318548202514648f * float(lane_0) / 2048.0f;
                float _S18 = cos(a1_0);

#line 27
                float _S19 = sin(a1_0);

#line 27
                k2_1 = 0U;

#line 27
                cr_0 = 1.0f;

#line 27
                ci_0 = 0.0f;

                for(;;)
                {

#line 29
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 29
                        break;
                    }

#line 30
                    (*r_4)[k2_1] = cmul_0((*r_4)[k2_1], float2(cr_0, ci_0));
                    float nr_0 = cr_0 * _S18 - ci_0 * _S19;
                    float _S20 = cr_0 * _S19 + ci_0 * _S18;

#line 29
                    k2_1 = k2_1 + 1U;

#line 29
                    cr_0 = nr_0;

#line 29
                    ci_0 = _S20;

#line 29
                }

#line 39
                uint _S21 = max(128U, 1U);

#line 39
                uint _S22 = 16U / _S21;
                uint _S23 = max(8U, 1U);

#line 40
                _S17 = _S23;
                uint _S24 = tid_0 / _S23;

#line 41
                uint _S25 = tid_0 % _S23;

#line 41
                d_2 = 0U;
                for(;;)
                {

#line 42
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 42
                        break;
                    }

#line 43
                    uint j_2 = d_2 / _S21;

#line 43
                    uint m_0 = d_2 % _S21;
                    want_1[d_2] = _S24 * 128U + _S25 + _S23 * d_2;

#line 42
                    d_2 = d_2 + 1U;

#line 42
                }

#line 42
                thread array<uint, int(16)> _S26 = want_1;

#line 42
                exchange_0(r_4, &_S26, lgLn_0, lgTB_0, kernelContext_3);

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
                thread array<uint, int(16)> want_2;

#line 7
                z_1 = 0U;
                for(;;)
                {

#line 8
                    if(z_1 < 16U)
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



                uint lgTB_1 = firstbithigh_0(8U);

                uint _S27 = tid_0 >> lgTB_1;
                uint lane_1 = tid_0 & 7U;


                dft16_0(r_4);

#line 26
                float a1_1 = 6.28318548202514648f * float(lane_1) / 128.0f;
                float _S28 = cos(a1_1);

#line 27
                float _S29 = sin(a1_1);

#line 27
                k2_1 = 0U;

#line 27
                cr_0 = 1.0f;

#line 27
                ci_0 = 0.0f;

                for(;;)
                {

#line 29
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 29
                        break;
                    }

#line 30
                    (*r_4)[k2_1] = cmul_0((*r_4)[k2_1], float2(cr_0, ci_0));
                    float nr_1 = cr_0 * _S28 - ci_0 * _S29;
                    float _S30 = cr_0 * _S29 + ci_0 * _S28;

#line 29
                    k2_1 = k2_1 + 1U;

#line 29
                    cr_0 = nr_1;

#line 29
                    ci_0 = _S30;

#line 29
                }

#line 39
                uint _S31 = 16U / _S17;
                uint _S32 = max(0U, 1U);
                uint _S33 = tid_0 / _S32;

#line 41
                uint _S34 = tid_0 % _S32;

#line 41
                d_2 = 0U;
                for(;;)
                {

#line 42
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 42
                        break;
                    }

#line 43
                    uint j_3 = d_2 / _S17;

#line 43
                    uint m_1 = d_2 % _S17;
                    want_2[d_2] = _S27 * 128U + (lane_1 * _S31 + j_3) * 8U + m_1;

#line 42
                    d_2 = d_2 + 1U;

#line 42
                }

#line 42
                thread array<uint, int(16)> _S35 = want_2;

#line 42
                exchange_0(r_4, &_S35, _S16, lgTB_1, kernelContext_3);

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
    innermost_0(r_4);

#line 864 "/tmp/tmp7pah8ipj/forward.slang"
    return;
}


#line 430
uint lgOf_0(uint i_4)
{

#line 430
    uint _S36;

#line 430
    if(i_4 < 2U)
    {

#line 430
        _S36 = 4U;

#line 430
    }
    else
    {

#line 430
        if(i_4 == 2U)
        {

#line 430
            _S36 = 3U;

#line 430
        }
        else
        {

#line 430
            _S36 = 1U;

#line 430
        }

#line 430
    }

#line 430
    return _S36;
}


#line 432
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(2U);

    uint x_0 = slot_0 >> lg_0;

#line 436
    uint lg_1 = lgOf_0(1U);

#line 436
    uint lg_2 = lgOf_0(0U);

#line 441
    return (((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | ((x_0 >> lg_1) & ((1U << lg_2) - 1U));
}


#line 869
[[kernel]] void seriesForward(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_series_1 [[buffer(1)]], uint device* entryPointParams_starts_1 [[buffer(2)]], packed_float2 device* entryPointParams_spectra_1 [[buffer(3)]])
{

#line 869
    thread KernelContext_0 kernelContext_4;

#line 869
    (&kernelContext_4)->entryPointParams_0 = entryPointParams_1;

#line 869
    (&kernelContext_4)->entryPointParams_series_0 = entryPointParams_series_1;

#line 869
    (&kernelContext_4)->entryPointParams_starts_0 = entryPointParams_starts_1;

#line 869
    (&kernelContext_4)->entryPointParams_spectra_0 = entryPointParams_spectra_1;

#line 869
    threadgroup array<uint, int(2048)> stg_1;

#line 869
    (&kernelContext_4)->stg_0 = &stg_1;

#line 875
    uint tid_1 = lid_0.x;
    (&kernelContext_4)->_tid_0 = tid_1;
    (&kernelContext_4)->_stgBase_0 = 0U;
    uint _S37 = gid_0.x;

#line 878
    uint _S38 = entryPointParams_starts_1[_S37];
    thread array<float2, int(16)> r_5;

#line 879
    uint k_1 = 0U;
    for(;;)
    {

#line 880
        if(k_1 < 16U)
        {
        }
        else
        {

#line 880
            break;
        }

#line 881
        uint offset_0 = tid_1 + 128U * k_1;
        float2 _S39 = float2(0.0f, 0.0f);

#line 882
        bool _S40;

        if(_S38 < ((&kernelContext_4)->entryPointParams_0->seriesLength_0))
        {

#line 884
            _S40 = offset_0 < ((&kernelContext_4)->entryPointParams_0->seriesLength_0 - _S38);

#line 884
        }
        else
        {

#line 884
            _S40 = false;

#line 884
        }

#line 884
        float2 x_1;

#line 884
        if(_S40)
        {

#line 884
            x_1 = float2(*((&kernelContext_4)->entryPointParams_series_0+(_S38 + offset_0))) ;

#line 884
        }
        else
        {

#line 884
            x_1 = _S39;

#line 884
        }

        r_5[k_1] = float2(x_1.x / 2048.0f, - x_1.y / 2048.0f);

#line 880
        k_1 = k_1 + 1U;

#line 880
    }

#line 880
    forwardTransform_0(&r_5, tid_1, &kernelContext_4);

#line 880
    k_1 = 0U;

#line 889
    for(;;)
    {

#line 889
        if(k_1 < 16U)
        {
        }
        else
        {

#line 889
            break;
        }

#line 889
        *((&kernelContext_4)->entryPointParams_spectra_0+(_S37 * 2048U + slotToIndex_0(tid_1 * 16U + k_1))) = packed_float2(float2(r_5[k_1].x, - r_5[k_1].y)) ;

#line 889
        k_1 = k_1 + 1U;

#line 889
    }



    return;
}
