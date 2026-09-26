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


#line 116 "/tmp/mf-committed-check/python/matchedfilter/metal/mm_2048_fusedTierB.slang"
float2 cload_0(packed_float2 device* b_0, uint i_0)
{

#line 116
    return float2(*(b_0+i_0)) ;
}


#line 156
float2 cmulConj_0(float2 a_0, float2 b_1)
{

#line 156
    float _S2 = a_0.x;

#line 156
    float _S3 = b_1.x;

#line 156
    float _S4 = a_0.y;

#line 156
    float _S5 = b_1.y;

#line 156
    return float2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 305
void r4_0(float2 thread* a_1, float2 thread* b_2, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_1 + *c_0;

#line 307
    float2 t1_0 = *a_1 - *c_0;

#line 307
    float2 t2_0 = *b_2 + *d_0;

#line 307
    float2 t3_0 = *b_2 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_1 = t0_0 + t2_0;

#line 309
    *b_2 = t1_0 + j3_0;

#line 309
    *c_0 = t0_0 - t2_0;

#line 309
    *d_0 = t1_0 - j3_0;
    return;
}


#line 155
float2 cmul_0(float2 a_2, float2 b_3)
{

#line 155
    float _S6 = a_2.x;

#line 155
    float _S7 = b_3.x;

#line 155
    float _S8 = a_2.y;

#line 155
    float _S9 = b_3.y;

#line 155
    return float2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 341
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 348
    uint n1_0 = 0U;
    for(;;)
    {

#line 349
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 349
            break;
        }

#line 349
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 349
        n1_0 = n1_0 + 1U;

#line 349
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 350
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 350
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 351
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 351
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 352
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 352
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 352
    uint k2_0 = 0U;
    for(;;)
    {

#line 353
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 353
            break;
        }

#line 353
        uint _S10 = 4U * k2_0;

#line 353
        r4_0(&(*r_0)[_S10], &(*r_0)[_S10 + 1U], &(*r_0)[_S10 + 2U], &(*r_0)[_S10 + 3U]);

#line 353
        k2_0 = k2_0 + 1U;

#line 353
    }

    float2 t_0 = (*r_0)[int(1)];

#line 355
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 355
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 356
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 356
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 357
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 357
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 358
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 358
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 359
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 359
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 360
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 360
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


#line 144 "/tmp/mf-committed-check/python/matchedfilter/metal/mm_2048_fusedTierB.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_data_0;
    packed_float2 device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    uint _stgBase_0;
    uint _tid_0;
    array<uint, int(4096)> threadgroup* stg_0;
};


#line 144
void stgPut_0(uint i_1, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 144
    uint _S11 = 2U * i_1;

#line 144
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S11] = (as_type<uint>((v_0.x)));

#line 144
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S11 + 1U] = (as_type<uint>((v_0.y)));

#line 144
    return;
}


#line 145
float2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 145
    uint _S12 = 2U * i_2;

#line 145
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S12]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S12 + 1U]))));
}


#line 382
void exchange_0(array<float2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 382
    uint j_0;

#line 393
    thread array<float2, int(16)> out_0;

#line 393
    uint z_0 = 0U;
    for(;;)
    {

#line 394
        if(z_0 < 16U)
        {
        }
        else
        {

#line 394
            break;
        }

#line 394
        out_0[z_0] = float2(0.0f, 0.0f);

#line 394
        z_0 = z_0 + 1U;

#line 394
    }
    uint _S13 = (1U << lgSpan_0) - 1U;
    uint _S14 = (1U << lgLen_0) - 1U;

#line 396
    uint c_1 = 0U;
    for(;;)
    {

#line 397
        if(c_1 < 1U)
        {
        }
        else
        {

#line 397
            break;
        }

#line 398
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 398
        j_0 = 0U;
        for(;;)
        {

#line 399
            if(j_0 < 16U)
            {
            }
            else
            {

#line 399
                break;
            }

#line 399
            stgPut_0(j_0 * 128U + kernelContext_2->_tid_0, (*r_1)[c_1 * 16U + j_0], kernelContext_2);

#line 399
            j_0 = j_0 + 1U;

#line 399
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 400
        uint d_1 = 0U;
        for(;;)
        {

#line 401
            if(d_1 < 16U)
            {
            }
            else
            {

#line 401
                break;
            }
            uint b_4 = ((*want_0)[d_1]) >> lgLen_0;

#line 403
            uint rem_0 = ((*want_0)[d_1]) & _S14;
            uint i_3 = rem_0 >> lgSpan_0;

#line 404
            uint ln_0 = rem_0 & _S13;
            uint _S15 = c_1 * 16U;

#line 405
            bool _S16;

#line 405
            if(i_3 >= _S15)
            {

#line 405
                _S16 = i_3 < ((c_1 + 1U) * 16U);

#line 405
            }
            else
            {

#line 405
                _S16 = false;

#line 405
            }

#line 405
            if(_S16)
            {

#line 405
                float2 _S17 = stgGet_0((i_3 - _S15) * 128U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S17;

#line 405
            }

#line 401
            d_1 = d_1 + 1U;

#line 401
        }

#line 397
        c_1 = c_1 + 1U;

#line 397
    }

#line 397
    j_0 = 0U;

#line 409
    for(;;)
    {

#line 409
        if(j_0 < 16U)
        {
        }
        else
        {

#line 409
            break;
        }

#line 409
        (*r_1)[j_0] = out_0[j_0];

#line 409
        j_0 = j_0 + 1U;

#line 409
    }
    return;
}


#line 325
void dft8_0(array<float2, int(16)> thread* r_2, uint o_0)
{


    thread array<float2, int(8)> b_5;

#line 329
    uint s_0 = 1U;
    for(;;)
    {

#line 330
        if(s_0 < 8U)
        {
        }
        else
        {

#line 330
            break;
        }

#line 330
        uint j_1 = 0U;
        for(;;)
        {

#line 331
            if(j_1 < 4U)
            {
            }
            else
            {

#line 331
                break;
            }

#line 332
            uint k_0 = j_1 & (s_0 - 1U);
            float ang_0 = 3.14159274101257324f * float(k_0) / float(s_0);

            uint _S18 = o_0 + j_1;

#line 335
            float2 t_6 = cmul_0(float2(cos(ang_0), sin(ang_0)), (*r_2)[_S18 + 4U]);
            uint _S19 = ((j_1 - k_0) << 1U) + k_0;

#line 336
            b_5[_S19] = (*r_2)[_S18] + t_6;

#line 336
            b_5[_S19 + s_0] = (*r_2)[_S18] - t_6;

#line 331
            j_1 = j_1 + 1U;

#line 331
        }

#line 331
        uint i_4 = 0U;

#line 338
        for(;;)
        {

#line 338
            if(i_4 < 8U)
            {
            }
            else
            {

#line 338
                break;
            }

#line 338
            (*r_2)[o_0 + i_4] = b_5[i_4];

#line 338
            i_4 = i_4 + 1U;

#line 338
        }

#line 330
        s_0 = s_0 << 1U;

#line 330
    }

#line 340
    return;
}


#line 366
void innermost_0(array<float2, int(16)> thread* r_3)
{

#line 366
    uint b_6 = 0U;


    for(;;)
    {

#line 369
        if(b_6 < 2U)
        {
        }
        else
        {

#line 369
            break;
        }

#line 369
        dft8_0(r_3, b_6 * 8U);

#line 369
        b_6 = b_6 + 1U;

#line 369
    }


    return;
}


#line 431
uint lgOf_0(uint i_5)
{

#line 431
    uint _S20;

#line 431
    if(i_5 < 2U)
    {

#line 431
        _S20 = 4U;

#line 431
    }
    else
    {

#line 431
        if(i_5 == 2U)
        {

#line 431
            _S20 = 3U;

#line 431
        }
        else
        {

#line 431
            _S20 = 1U;

#line 431
        }

#line 431
    }

#line 431
    return _S20;
}


#line 433
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(2U);

    uint x_0 = slot_0 >> lg_0;

#line 437
    uint lg_1 = lgOf_0(1U);

#line 437
    uint lg_2 = lgOf_0(0U);

#line 442
    return (((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | ((x_0 >> lg_1) & ((1U << lg_2) - 1U));
}


#line 462
void filterPair_0(uint pair_0, uint tid_0, packed_float2 device* data_0, packed_float2 device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint ntmpl_1, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{


    uint z_1;

#line 466
    uint _S21;

#line 466
    uint k2_1;

#line 466
    float cr_0;

#line 466
    float ci_0;

#line 466
    uint _S22;

#line 466
    uint d_2;

#line 466
    bool live_0;



    kernelContext_3->_tid_0 = tid_0;
    uint _S23 = pair_0 / ntmpl_1;

#line 471
    uint _S24 = pair_0 % ntmpl_1;

    thread array<float2, int(16)> r_4;

#line 473
    uint n2_0 = 0U;

#line 484
    for(;;)
    {

#line 484
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 484
            break;
        }

#line 485
        uint idx_0 = tid_0 + 128U * n2_0;
        r_4[n2_0] = cmulConj_0(cload_0(data_0, _S23 * 2048U + idx_0), cload_0(tmpl_0, _S24 * 2048U + idx_0));

#line 484
        n2_0 = n2_0 + 1U;

#line 484
    }

#line 484
    for(;;)
    {

#line 484
        for(;;)
        {

#line 490
            for(;;)
            {

#line 491
                thread array<uint, int(16)> want_1;

#line 491
                z_1 = 0U;
                for(;;)
                {

#line 492
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 492
                        break;
                    }

#line 492
                    want_1[z_1] = 0U;

#line 492
                    z_1 = z_1 + 1U;

#line 492
                }



                uint lgTB_0 = firstbithigh_0(128U);

#line 496
                _S21 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(2048U);

                uint lane_0 = tid_0 & 127U;

                dft16_0(&r_4);

#line 506
                float a1_0 = 6.28318548202514648f * float(lane_0) / 2048.0f;
                float _S25 = cos(a1_0);

#line 507
                float _S26 = sin(a1_0);

#line 507
                k2_1 = 0U;

#line 507
                cr_0 = 1.0f;

#line 507
                ci_0 = 0.0f;

                for(;;)
                {

#line 509
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 509
                        break;
                    }

#line 510
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cr_0, ci_0));
                    float nr_0 = cr_0 * _S25 - ci_0 * _S26;
                    float _S27 = cr_0 * _S26 + ci_0 * _S25;

#line 509
                    k2_1 = k2_1 + 1U;

#line 509
                    cr_0 = nr_0;

#line 509
                    ci_0 = _S27;

#line 509
                }

#line 519
                uint _S28 = max(128U, 1U);

#line 519
                uint _S29 = 16U / _S28;
                uint _S30 = max(8U, 1U);

#line 520
                _S22 = _S30;
                uint _S31 = tid_0 / _S30;

#line 521
                uint _S32 = tid_0 % _S30;

#line 521
                d_2 = 0U;
                for(;;)
                {

#line 522
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 522
                        break;
                    }

#line 523
                    uint j_2 = d_2 / _S28;

#line 523
                    uint m_0 = d_2 % _S28;
                    want_1[d_2] = _S31 * 128U + _S32 + _S30 * d_2;

#line 522
                    d_2 = d_2 + 1U;

#line 522
                }

#line 522
                thread array<uint, int(16)> _S33 = want_1;

#line 522
                exchange_0(&r_4, &_S33, lgLn_0, lgTB_0, kernelContext_3);

#line 490
                break;
            }

#line 490
            break;
        }

#line 490
        for(;;)
        {

#line 490
            for(;;)
            {

#line 491
                thread array<uint, int(16)> want_2;

#line 491
                z_1 = 0U;
                for(;;)
                {

#line 492
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 492
                        break;
                    }

#line 492
                    want_2[z_1] = 0U;

#line 492
                    z_1 = z_1 + 1U;

#line 492
                }



                uint lgTB_1 = firstbithigh_0(8U);

                uint _S34 = tid_0 >> lgTB_1;
                uint lane_1 = tid_0 & 7U;

                dft16_0(&r_4);

#line 506
                float a1_1 = 6.28318548202514648f * float(lane_1) / 128.0f;
                float _S35 = cos(a1_1);

#line 507
                float _S36 = sin(a1_1);

#line 507
                k2_1 = 0U;

#line 507
                cr_0 = 1.0f;

#line 507
                ci_0 = 0.0f;

                for(;;)
                {

#line 509
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 509
                        break;
                    }

#line 510
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cr_0, ci_0));
                    float nr_1 = cr_0 * _S35 - ci_0 * _S36;
                    float _S37 = cr_0 * _S36 + ci_0 * _S35;

#line 509
                    k2_1 = k2_1 + 1U;

#line 509
                    cr_0 = nr_1;

#line 509
                    ci_0 = _S37;

#line 509
                }

#line 519
                uint _S38 = 16U / _S22;
                uint _S39 = max(0U, 1U);
                uint _S40 = tid_0 / _S39;

#line 521
                uint _S41 = tid_0 % _S39;

#line 521
                d_2 = 0U;
                for(;;)
                {

#line 522
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 522
                        break;
                    }

#line 523
                    uint j_3 = d_2 / _S22;

#line 523
                    uint m_1 = d_2 % _S22;
                    want_2[d_2] = _S34 * 128U + (lane_1 * _S38 + j_3) * 8U + m_1;

#line 522
                    d_2 = d_2 + 1U;

#line 522
                }

#line 522
                thread array<uint, int(16)> _S42 = want_2;

#line 522
                exchange_0(&r_4, &_S42, _S21, lgTB_1, kernelContext_3);

#line 490
                break;
            }

#line 490
            break;
        }

#line 490
        break;
    }

#line 530
    innermost_0(&r_4);

#line 543
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 543
    uint b_7 = tid_0;

#line 551
    for(;;)
    {

#line 551
        if(b_7 < nbins_1)
        {
        }
        else
        {

#line 551
            break;
        }

#line 551
        (*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_7] = thrBits_1;

#line 551
        b_7 = b_7 + 128U;

#line 551
    }

    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;
    thread array<uint, int(16)> myBin_0;

#line 556
    uint i_6 = 0U;
    for(;;)
    {

#line 557
        if(i_6 < 16U)
        {
        }
        else
        {

#line 557
            break;
        }

#line 558
        uint idx_1 = slotToIndex_0(tid_0 * 16U + i_6);
        if(idx_1 >= winStart_1)
        {

#line 559
            live_0 = idx_1 < winEnd_1;

#line 559
        }
        else
        {

#line 559
            live_0 = false;

#line 559
        }



        float _rx_0 = r_4[i_6].x;

#line 563
        float _ry_0 = r_4[i_6].y;
        if(live_0)
        {

#line 564
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 564
        }
        else
        {

#line 564
            n2_0 = 0U;

#line 564
        }

#line 564
        myMag_0[i_6] = n2_0;
        uint off_0 = idx_1 - winStart_1;

#line 572
        if(live_0)
        {

#line 572
            if(binShift_1 >= int(0))
            {

#line 572
                z_1 = off_0 >> uint(binShift_1);

#line 572
            }
            else
            {

#line 572
                uint _S43 = off_0 / binsize_1;

#line 572
                z_1 = _S43;

#line 572
            }

#line 572
        }
        else
        {

#line 572
            z_1 = 0U;

#line 572
        }

#line 572
        myBin_0[i_6] = z_1;

#line 572
        bool _S44;



        if(nbins_1 > 1U)
        {

#line 576
            _S44 = (myMag_0[i_6]) > thrBits_1;

#line 576
        }
        else
        {

#line 576
            _S44 = false;

#line 576
        }

#line 576
        if(_S44)
        {

#line 577
            uint _S45 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_6]])), myMag_0[i_6], memory_order_relaxed);

#line 576
        }

#line 557
        i_6 = i_6 + 1U;

#line 557
    }

#line 589
    if(nbins_1 == 1U)
    {

#line 589
        i_6 = 0U;

#line 589
        uint bestBits_0 = thrBits_1;


        for(;;)
        {

#line 592
            if(i_6 < 16U)
            {
            }
            else
            {

#line 592
                break;
            }

#line 592
            uint _S46 = max(bestBits_0, myMag_0[i_6]);

#line 592
            i_6 = i_6 + 1U;

#line 592
            bestBits_0 = _S46;

#line 592
        }

        uint wm_0 = simd_max(bestBits_0);
        bool _S47 = simd_is_first();

#line 595
        if(_S47)
        {

#line 595
            live_0 = wm_0 > thrBits_1;

#line 595
        }
        else
        {

#line 595
            live_0 = false;

#line 595
        }

#line 595
        if(live_0)
        {

#line 595
            uint _S48 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0])), wm_0, memory_order_relaxed);

#line 595
        }

#line 589
    }

#line 610
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 610
    i_6 = 0U;

#line 615
    for(;;)
    {

#line 615
        if(i_6 < 16U)
        {
        }
        else
        {

#line 615
            break;
        }



        if((myMag_0[i_6]) > thrBits_1)
        {

#line 620
            live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_6]]) == myMag_0[i_6];

#line 620
        }
        else
        {

#line 620
            live_0 = false;

#line 620
        }

#line 620
        if(live_0)
        {

#line 621
            uint o_1 = pair_0 * nbins_1 + myBin_0[i_6];

            *(peakIdx_0+o_1) = int(slotToIndex_0(tid_0 * 16U + i_6));

#line 623
            *(peakVal_0+o_1) = packed_float2(float2(r_4[i_6].x, r_4[i_6].y)) ;

#line 620
        }

#line 615
        i_6 = i_6 + 1U;

#line 615
    }

#line 615
    b_7 = tid_0;

#line 634
    for(;;)
    {

#line 634
        if(b_7 < nbins_1)
        {
        }
        else
        {

#line 634
            break;
        }

#line 635
        if(((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_7]) == thrBits_1)
        {

#line 636
            uint o_2 = pair_0 * nbins_1 + b_7;

            *(peakIdx_0+o_2) = int(-1);

#line 638
            *(peakVal_0+o_2) = packed_float2(float2(0.0f, 0.0f)) ;

#line 635
        }

#line 634
        b_7 = b_7 + 128U;

#line 634
    }

#line 642
    return;
}


#line 806
[[kernel]] void fusedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]])
{

#line 806
    thread KernelContext_0 kernelContext_4;

#line 806
    (&kernelContext_4)->entryPointParams_0 = entryPointParams_1;

#line 806
    (&kernelContext_4)->entryPointParams_data_0 = entryPointParams_data_1;

#line 806
    (&kernelContext_4)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 806
    (&kernelContext_4)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 806
    (&kernelContext_4)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 806
    threadgroup array<uint, int(4096)> stg_1;

#line 806
    (&kernelContext_4)->stg_0 = &stg_1;

#line 823
    uint _pr_0 = gid_0.x;

#line 823
    uint _t_0 = lid_0.x;
    (&kernelContext_4)->_stgBase_0 = 0U;

#line 824
    filterPair_0(_pr_0, _t_0, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_4);

#line 832
    return;
}

