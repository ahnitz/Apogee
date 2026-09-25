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


#line 116 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_8192_refineListed.slang"
float2 cload_0(packed_float2 device* b_0, uint i_0)
{

#line 116
    return float2(*(b_0+i_0)) ;
}


#line 152
float2 cmulConj_0(float2 a_0, float2 b_1)
{

#line 152
    float _S2 = a_0.x;

#line 152
    float _S3 = b_1.x;

#line 152
    float _S4 = a_0.y;

#line 152
    float _S5 = b_1.y;

#line 152
    return float2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 301
void r4_0(float2 thread* a_1, float2 thread* b_2, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_1 + *c_0;

#line 303
    float2 t1_0 = *a_1 - *c_0;

#line 303
    float2 t2_0 = *b_2 + *d_0;

#line 303
    float2 t3_0 = *b_2 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_1 = t0_0 + t2_0;

#line 305
    *b_2 = t1_0 + j3_0;

#line 305
    *c_0 = t0_0 - t2_0;

#line 305
    *d_0 = t1_0 - j3_0;
    return;
}


#line 151
float2 cmul_0(float2 a_2, float2 b_3)
{

#line 151
    float _S6 = a_2.x;

#line 151
    float _S7 = b_3.x;

#line 151
    float _S8 = a_2.y;

#line 151
    float _S9 = b_3.y;

#line 151
    return float2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 337
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 344
    uint n1_0 = 0U;
    for(;;)
    {

#line 345
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 345
            break;
        }

#line 345
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 345
        n1_0 = n1_0 + 1U;

#line 345
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 346
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 346
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 347
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 347
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 348
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 348
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 348
    uint k2_0 = 0U;
    for(;;)
    {

#line 349
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 349
            break;
        }

#line 349
        uint _S10 = 4U * k2_0;

#line 349
        r4_0(&(*r_0)[_S10], &(*r_0)[_S10 + 1U], &(*r_0)[_S10 + 2U], &(*r_0)[_S10 + 3U]);

#line 349
        k2_0 = k2_0 + 1U;

#line 349
    }

    float2 t_0 = (*r_0)[int(1)];

#line 351
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 351
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 352
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 352
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 353
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 353
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 354
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 354
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 355
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 355
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 356
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 356
    (*r_0)[int(14)] = t_5;
    return;
}


#line 8599 "hlsl.meta.slang"
struct EntryPointParams_0
{
    uint ntmpl_0;
    uint winStart_0;
    uint winEnd_0;
    uint binsize_0;
    int binShift_0;
    uint nbins_0;
    uint thrBits_0;
};


#line 140 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_8192_refineListed.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_data_0;
    packed_float2 device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    uint device* entryPointParams_survivors_0;
    uint _stgBase_0;
    uint _tid_0;
    array<uint, int(16384)> threadgroup* stg_0;
};


#line 140
void stgPut_0(uint i_1, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 140
    uint _S11 = 2U * i_1;

#line 140
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S11] = (as_type<uint>((v_0.x)));

#line 140
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S11 + 1U] = (as_type<uint>((v_0.y)));

#line 140
    return;
}


#line 141
float2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 141
    uint _S12 = 2U * i_2;

#line 141
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S12]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S12 + 1U]))));
}


#line 378
void exchange_0(array<float2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 378
    uint j_0;

#line 389
    thread array<float2, int(16)> out_0;

#line 389
    uint z_0 = 0U;
    for(;;)
    {

#line 390
        if(z_0 < 16U)
        {
        }
        else
        {

#line 390
            break;
        }

#line 390
        out_0[z_0] = float2(0.0f, 0.0f);

#line 390
        z_0 = z_0 + 1U;

#line 390
    }
    uint _S13 = (1U << lgSpan_0) - 1U;
    uint _S14 = (1U << lgLen_0) - 1U;

#line 392
    uint c_1 = 0U;
    for(;;)
    {

#line 393
        if(c_1 < 1U)
        {
        }
        else
        {

#line 393
            break;
        }

#line 394
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 394
        j_0 = 0U;
        for(;;)
        {

#line 395
            if(j_0 < 16U)
            {
            }
            else
            {

#line 395
                break;
            }

#line 395
            stgPut_0(j_0 * 512U + kernelContext_2->_tid_0, (*r_1)[c_1 * 16U + j_0], kernelContext_2);

#line 395
            j_0 = j_0 + 1U;

#line 395
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 396
        uint d_1 = 0U;
        for(;;)
        {

#line 397
            if(d_1 < 16U)
            {
            }
            else
            {

#line 397
                break;
            }
            uint b_4 = ((*want_0)[d_1]) >> lgLen_0;

#line 399
            uint rem_0 = ((*want_0)[d_1]) & _S14;
            uint i_3 = rem_0 >> lgSpan_0;

#line 400
            uint ln_0 = rem_0 & _S13;
            uint _S15 = c_1 * 16U;

#line 401
            bool _S16;

#line 401
            if(i_3 >= _S15)
            {

#line 401
                _S16 = i_3 < ((c_1 + 1U) * 16U);

#line 401
            }
            else
            {

#line 401
                _S16 = false;

#line 401
            }

#line 401
            if(_S16)
            {

#line 401
                float2 _S17 = stgGet_0((i_3 - _S15) * 512U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S17;

#line 401
            }

#line 397
            d_1 = d_1 + 1U;

#line 397
        }

#line 393
        c_1 = c_1 + 1U;

#line 393
    }

#line 393
    j_0 = 0U;

#line 405
    for(;;)
    {

#line 405
        if(j_0 < 16U)
        {
        }
        else
        {

#line 405
            break;
        }

#line 405
        (*r_1)[j_0] = out_0[j_0];

#line 405
        j_0 = j_0 + 1U;

#line 405
    }
    return;
}


#line 312
void dft2_0(array<float2, int(16)> thread* r_2, uint o_0)
{
    float2 a_3 = (*r_2)[o_0];

#line 314
    float2 b_5 = (*r_2)[o_0 + 1U];

#line 314
    (*r_2)[o_0] = (*r_2)[o_0] + (*r_2)[o_0 + 1U];

#line 314
    (*r_2)[o_0 + 1U] = a_3 - b_5;
    return;
}


#line 362
void innermost_0(array<float2, int(16)> thread* r_3)
{

#line 362
    uint b_6 = 0U;

#line 367
    for(;;)
    {

#line 367
        if(b_6 < 8U)
        {
        }
        else
        {

#line 367
            break;
        }

#line 367
        dft2_0(r_3, b_6 * 2U);

#line 367
        b_6 = b_6 + 1U;

#line 367
    }
    return;
}


#line 427
uint lgOf_0(uint i_4)
{

#line 427
    uint _S18;

#line 427
    if(i_4 < 3U)
    {

#line 427
        _S18 = 4U;

#line 427
    }
    else
    {

#line 427
        _S18 = 1U;

#line 427
    }

#line 427
    return _S18;
}


#line 429
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(3U);

    uint x_0 = slot_0 >> lg_0;

#line 433
    uint lg_1 = lgOf_0(2U);

    uint x_1 = x_0 >> lg_1;

#line 433
    uint lg_2 = lgOf_0(1U);

#line 433
    uint lg_3 = lgOf_0(0U);

#line 438
    return (((((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | (x_1 & ((1U << lg_2) - 1U))) << lg_3) | ((x_1 >> lg_2) & ((1U << lg_3) - 1U));
}


#line 448
void filterOne_0(uint pair_0, uint d_2, uint t_6, uint tid_0, const array<float2, int(16)> thread* dreg_0, packed_float2 device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{


    uint z_1;

#line 452
    uint _S19;

#line 452
    uint k2_1;

#line 452
    uint _S20;

#line 452
    uint d_3;

#line 452
    uint _S21;

#line 452
    uint _S22;

#line 452
    bool live_0;

    thread array<float2, int(16)> r_4;

#line 454
    uint n2_0 = 0U;


    for(;;)
    {

#line 457
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 457
            break;
        }

#line 458
        r_4[n2_0] = cmulConj_0((*dreg_0)[n2_0], cload_0(tmpl_0, t_6 * 8192U + tid_0 + 512U * n2_0));

#line 457
        n2_0 = n2_0 + 1U;

#line 457
    }

#line 457
    for(;;)
    {

#line 457
        for(;;)
        {

            for(;;)
            {

#line 461
                thread array<uint, int(16)> want_1;

#line 461
                z_1 = 0U;
                for(;;)
                {

#line 462
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 462
                        break;
                    }

#line 462
                    want_1[z_1] = 0U;

#line 462
                    z_1 = z_1 + 1U;

#line 462
                }



                uint lgTB_0 = firstbithigh_0(512U);

#line 466
                _S19 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(8192U);

                uint _S23 = tid_0 & 511U;

                dft16_0(&r_4);

#line 471
                k2_1 = 0U;
                for(;;)
                {

#line 472
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 472
                        break;
                    }

#line 473
                    float ang_0 = 6.28318548202514648f * float(_S23 * k2_1) / 8192.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cos(ang_0), sin(ang_0)));

#line 472
                    k2_1 = k2_1 + 1U;

#line 472
                }

#line 479
                uint _S24 = max(512U, 1U);

#line 479
                uint _S25 = 16U / _S24;
                uint _S26 = max(32U, 1U);

#line 480
                _S20 = _S26;
                uint _S27 = tid_0 / _S26;

#line 481
                uint _S28 = tid_0 % _S26;

#line 481
                d_3 = 0U;
                for(;;)
                {

#line 482
                    if(d_3 < 16U)
                    {
                    }
                    else
                    {

#line 482
                        break;
                    }

#line 483
                    uint j_1 = d_3 / _S24;

#line 483
                    uint m_0 = d_3 % _S24;
                    want_1[d_3] = _S27 * 512U + _S28 + _S26 * d_3;

#line 482
                    d_3 = d_3 + 1U;

#line 482
                }

#line 482
                thread array<uint, int(16)> _S29 = want_1;

#line 482
                exchange_0(&r_4, &_S29, lgLn_0, lgTB_0, kernelContext_3);

#line 460
                break;
            }

#line 460
            break;
        }

#line 460
        for(;;)
        {

#line 460
            for(;;)
            {

#line 461
                thread array<uint, int(16)> want_2;

#line 461
                z_1 = 0U;
                for(;;)
                {

#line 462
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 462
                        break;
                    }

#line 462
                    want_2[z_1] = 0U;

#line 462
                    z_1 = z_1 + 1U;

#line 462
                }



                uint lgTB_1 = firstbithigh_0(32U);

#line 466
                _S21 = lgTB_1;


                uint _S30 = tid_0 & 31U;

                dft16_0(&r_4);

#line 471
                k2_1 = 0U;
                for(;;)
                {

#line 472
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 472
                        break;
                    }

#line 473
                    float ang_1 = 6.28318548202514648f * float(_S30 * k2_1) / 512.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cos(ang_1), sin(ang_1)));

#line 472
                    k2_1 = k2_1 + 1U;

#line 472
                }

#line 479
                uint _S31 = 16U / _S20;
                uint _S32 = max(2U, 1U);

#line 480
                _S22 = _S32;
                uint _S33 = tid_0 / _S32;

#line 481
                uint _S34 = tid_0 % _S32;

#line 481
                d_3 = 0U;
                for(;;)
                {

#line 482
                    if(d_3 < 16U)
                    {
                    }
                    else
                    {

#line 482
                        break;
                    }

#line 483
                    uint j_2 = d_3 / _S20;

#line 483
                    uint m_1 = d_3 % _S20;
                    want_2[d_3] = _S33 * 32U + _S34 + _S32 * d_3;

#line 482
                    d_3 = d_3 + 1U;

#line 482
                }

#line 482
                thread array<uint, int(16)> _S35 = want_2;

#line 482
                exchange_0(&r_4, &_S35, _S19, lgTB_1, kernelContext_3);

#line 460
                break;
            }

#line 460
            break;
        }

#line 460
        for(;;)
        {

#line 460
            for(;;)
            {

#line 461
                thread array<uint, int(16)> want_3;

#line 461
                z_1 = 0U;
                for(;;)
                {

#line 462
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 462
                        break;
                    }

#line 462
                    want_3[z_1] = 0U;

#line 462
                    z_1 = z_1 + 1U;

#line 462
                }



                uint lgTB_2 = firstbithigh_0(2U);

                uint _S36 = tid_0 >> lgTB_2;
                uint _S37 = tid_0 & 1U;

                dft16_0(&r_4);

#line 471
                k2_1 = 0U;
                for(;;)
                {

#line 472
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 472
                        break;
                    }

#line 473
                    float ang_2 = 6.28318548202514648f * float(_S37 * k2_1) / 32.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cos(ang_2), sin(ang_2)));

#line 472
                    k2_1 = k2_1 + 1U;

#line 472
                }

#line 479
                uint _S38 = 16U / _S22;
                uint _S39 = max(0U, 1U);
                uint _S40 = tid_0 / _S39;

#line 481
                uint _S41 = tid_0 % _S39;

#line 481
                d_3 = 0U;
                for(;;)
                {

#line 482
                    if(d_3 < 16U)
                    {
                    }
                    else
                    {

#line 482
                        break;
                    }

#line 483
                    uint j_3 = d_3 / _S22;

#line 483
                    uint m_2 = d_3 % _S22;
                    want_3[d_3] = _S36 * 32U + (_S37 * _S38 + j_3) * 2U + m_2;

#line 482
                    d_3 = d_3 + 1U;

#line 482
                }

#line 482
                thread array<uint, int(16)> _S42 = want_3;

#line 482
                exchange_0(&r_4, &_S42, _S21, lgTB_2, kernelContext_3);

#line 460
                break;
            }

#line 460
            break;
        }

#line 460
        break;
    }

#line 490
    innermost_0(&r_4);

#line 503
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 503
    uint b_7 = tid_0;

#line 511
    for(;;)
    {

#line 511
        if(b_7 < nbins_1)
        {
        }
        else
        {

#line 511
            break;
        }

#line 511
        (*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_7] = thrBits_1;

#line 511
        b_7 = b_7 + 512U;

#line 511
    }

    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;
    thread array<uint, int(16)> myBin_0;

#line 516
    uint i_5 = 0U;
    for(;;)
    {

#line 517
        if(i_5 < 16U)
        {
        }
        else
        {

#line 517
            break;
        }

#line 518
        uint idx_0 = slotToIndex_0(tid_0 * 16U + i_5);
        if(idx_0 >= winStart_1)
        {

#line 519
            live_0 = idx_0 < winEnd_1;

#line 519
        }
        else
        {

#line 519
            live_0 = false;

#line 519
        }



        float _rx_0 = r_4[i_5].x;

#line 523
        float _ry_0 = r_4[i_5].y;
        if(live_0)
        {

#line 524
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 524
        }
        else
        {

#line 524
            n2_0 = 0U;

#line 524
        }

#line 524
        myMag_0[i_5] = n2_0;
        uint off_0 = idx_0 - winStart_1;

#line 532
        if(live_0)
        {

#line 532
            if(binShift_1 >= int(0))
            {

#line 532
                z_1 = off_0 >> uint(binShift_1);

#line 532
            }
            else
            {

#line 532
                uint _S43 = off_0 / binsize_1;

#line 532
                z_1 = _S43;

#line 532
            }

#line 532
        }
        else
        {

#line 532
            z_1 = 0U;

#line 532
        }

#line 532
        myBin_0[i_5] = z_1;

#line 532
        bool _S44;



        if(nbins_1 > 1U)
        {

#line 536
            _S44 = (myMag_0[i_5]) > thrBits_1;

#line 536
        }
        else
        {

#line 536
            _S44 = false;

#line 536
        }

#line 536
        if(_S44)
        {

#line 537
            uint _S45 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_5]])), myMag_0[i_5], memory_order_relaxed);

#line 536
        }

#line 517
        i_5 = i_5 + 1U;

#line 517
    }

#line 549
    if(nbins_1 == 1U)
    {

#line 549
        i_5 = 0U;

#line 549
        uint bestBits_0 = thrBits_1;


        for(;;)
        {

#line 552
            if(i_5 < 16U)
            {
            }
            else
            {

#line 552
                break;
            }

#line 552
            uint _S46 = max(bestBits_0, myMag_0[i_5]);

#line 552
            i_5 = i_5 + 1U;

#line 552
            bestBits_0 = _S46;

#line 552
        }

        uint wm_0 = simd_max(bestBits_0);
        bool _S47 = simd_is_first();

#line 555
        if(_S47)
        {

#line 555
            live_0 = wm_0 > thrBits_1;

#line 555
        }
        else
        {

#line 555
            live_0 = false;

#line 555
        }

#line 555
        if(live_0)
        {

#line 555
            uint _S48 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0])), wm_0, memory_order_relaxed);

#line 555
        }

#line 549
    }

#line 570
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 570
    i_5 = 0U;

#line 575
    for(;;)
    {

#line 575
        if(i_5 < 16U)
        {
        }
        else
        {

#line 575
            break;
        }



        if((myMag_0[i_5]) > thrBits_1)
        {

#line 580
            live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_5]]) == myMag_0[i_5];

#line 580
        }
        else
        {

#line 580
            live_0 = false;

#line 580
        }

#line 580
        if(live_0)
        {

#line 581
            uint o_1 = pair_0 * nbins_1 + myBin_0[i_5];

            *(peakIdx_0+o_1) = int(slotToIndex_0(tid_0 * 16U + i_5));

#line 583
            *(peakVal_0+o_1) = packed_float2(float2(r_4[i_5].x, r_4[i_5].y)) ;

#line 580
        }

#line 575
        i_5 = i_5 + 1U;

#line 575
    }

#line 575
    b_7 = tid_0;

#line 594
    for(;;)
    {

#line 594
        if(b_7 < nbins_1)
        {
        }
        else
        {

#line 594
            break;
        }

#line 595
        if(((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_7]) == thrBits_1)
        {

#line 596
            uint o_2 = pair_0 * nbins_1 + b_7;

            *(peakIdx_0+o_2) = int(-1);

#line 598
            *(peakVal_0+o_2) = packed_float2(float2(0.0f, 0.0f)) ;

#line 595
        }

#line 594
        b_7 = b_7 + 512U;

#line 594
    }

#line 602
    return;
}


#line 712
void filterPair_0(uint pair_1, uint tid_1, packed_float2 device* data_0, packed_float2 device* tmpl_1, int device* peakIdx_1, packed_float2 device* peakVal_1, uint ntmpl_1, uint winStart_2, uint winEnd_2, uint binsize_2, int binShift_2, uint nbins_2, uint thrBits_2, KernelContext_0 thread* kernelContext_4)
{

#line 718
    kernelContext_4->_tid_0 = tid_1;

#line 728
    uint _S49 = pair_1 / ntmpl_1;

#line 728
    uint _S50 = pair_1 % ntmpl_1;
    thread array<float2, int(16)> dreg_1;

#line 729
    uint n2_1 = 0U;
    for(;;)
    {

#line 730
        if(n2_1 < 16U)
        {
        }
        else
        {

#line 730
            break;
        }

#line 731
        dreg_1[n2_1] = cload_0(data_0, _S49 * 8192U + tid_1 + 512U * n2_1);

#line 730
        n2_1 = n2_1 + 1U;

#line 730
    }

#line 730
    uint k_0 = 0U;

#line 738
    for(;;)
    {

#line 738
        if(k_0 < 1U)
        {
        }
        else
        {

#line 738
            break;
        }

#line 739
        uint _S51 = pair_1 + k_0;

#line 739
        uint _S52 = _S50 + k_0;

#line 739
        thread array<float2, int(16)> _S53 = dreg_1;

#line 739
        filterOne_0(_S51, _S49, _S52, tid_1, &_S53, tmpl_1, peakIdx_1, peakVal_1, winStart_2, winEnd_2, binsize_2, binShift_2, nbins_2, thrBits_2, kernelContext_4);

#line 738
        k_0 = k_0 + 1U;

#line 738
    }



    return;
}


#line 869
[[kernel]] void refineListed(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]], uint device* entryPointParams_survivors_1 [[buffer(5)]])
{

#line 869
    thread KernelContext_0 kernelContext_5;

#line 869
    (&kernelContext_5)->entryPointParams_0 = entryPointParams_1;

#line 869
    (&kernelContext_5)->entryPointParams_data_0 = entryPointParams_data_1;

#line 869
    (&kernelContext_5)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 869
    (&kernelContext_5)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 869
    (&kernelContext_5)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 869
    (&kernelContext_5)->entryPointParams_survivors_0 = entryPointParams_survivors_1;

#line 869
    threadgroup array<uint, int(16384)> stg_1;

#line 869
    (&kernelContext_5)->stg_0 = &stg_1;

#line 878
    uint pair_2 = entryPointParams_survivors_1[gid_0.x];

#line 884
    (&kernelContext_5)->_stgBase_0 = 0U;

#line 884
    filterPair_0(pair_2, lid_0.x, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_5);


    return;
}

