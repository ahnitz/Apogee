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


#line 116 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_64_fusedTierB.slang"
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


#line 144 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_64_fusedTierB.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_data_0;
    packed_float2 device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    uint _stgBase_0;
    uint _tid_0;
    array<uint, int(128)> threadgroup* stg_0;
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
            stgPut_0(j_0 * 4U + kernelContext_2->_tid_0, (*r_1)[c_1 * 16U + j_0], kernelContext_2);

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
                float2 _S17 = stgGet_0((i_3 - _S15) * 4U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
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


#line 320
void dft4_0(array<float2, int(16)> thread* r_2, uint o_0)
{
    r4_0(&(*r_2)[o_0], &(*r_2)[o_0 + 1U], &(*r_2)[o_0 + 2U], &(*r_2)[o_0 + 3U]);
    float2 t_6 = (*r_2)[o_0 + 1U];

#line 323
    (*r_2)[o_0 + 1U] = (*r_2)[o_0 + 2U];

#line 323
    (*r_2)[o_0 + 2U] = t_6;
    return;
}


#line 366
void innermost_0(array<float2, int(16)> thread* r_3)
{

#line 366
    uint b_5 = 0U;



    for(;;)
    {

#line 370
        if(b_5 < 4U)
        {
        }
        else
        {

#line 370
            break;
        }

#line 370
        dft4_0(r_3, b_5 * 4U);

#line 370
        b_5 = b_5 + 1U;

#line 370
    }

    return;
}


#line 431
uint lgOf_0(uint i_4)
{

#line 431
    uint _S18;

#line 431
    if(i_4 < 1U)
    {

#line 431
        _S18 = 4U;

#line 431
    }
    else
    {

#line 431
        _S18 = 1U;

#line 431
    }

#line 431
    return _S18;
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


#line 452
void filterOne_0(uint pair_0, uint d_2, uint t_7, uint tid_0, const array<float2, int(16)> thread* dreg_0, packed_float2 device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{


    uint z_1;

#line 456
    bool live_0;

    thread array<float2, int(16)> r_4;

#line 458
    uint n2_0 = 0U;


    for(;;)
    {

#line 461
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 461
            break;
        }

#line 462
        r_4[n2_0] = cmulConj_0((*dreg_0)[n2_0], cload_0(tmpl_0, t_7 * 64U + tid_0 + 4U * n2_0));

#line 461
        n2_0 = n2_0 + 1U;

#line 461
    }

#line 461
    for(;;)
    {

#line 461
        for(;;)
        {

            for(;;)
            {

#line 465
                thread array<uint, int(16)> want_1;

#line 465
                z_1 = 0U;
                for(;;)
                {

#line 466
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 466
                        break;
                    }

#line 466
                    want_1[z_1] = 0U;

#line 466
                    z_1 = z_1 + 1U;

#line 466
                }



                uint lgTB_0 = firstbithigh_0(4U);
                uint lgLn_0 = firstbithigh_0(64U);
                uint _S19 = tid_0 >> lgTB_0;
                uint lane_0 = tid_0 & 3U;

                dft16_0(&r_4);

#line 480
                float a1_0 = 6.28318548202514648f * float(lane_0) / 64.0f;
                float _S20 = cos(a1_0);

#line 481
                float _S21 = sin(a1_0);

#line 481
                uint k2_1 = 0U;

#line 481
                float cr_0 = 1.0f;

#line 481
                float ci_0 = 0.0f;

                for(;;)
                {

#line 483
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 483
                        break;
                    }

#line 484
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cr_0, ci_0));
                    float nr_0 = cr_0 * _S20 - ci_0 * _S21;
                    float _S22 = cr_0 * _S21 + ci_0 * _S20;

#line 483
                    k2_1 = k2_1 + 1U;

#line 483
                    cr_0 = nr_0;

#line 483
                    ci_0 = _S22;

#line 483
                }

#line 493
                uint _S23 = max(4U, 1U);

#line 493
                uint _S24 = 16U / _S23;
                uint _S25 = max(0U, 1U);
                uint _S26 = tid_0 / _S25;

#line 495
                uint _S27 = tid_0 % _S25;

#line 495
                uint d_3 = 0U;
                for(;;)
                {

#line 496
                    if(d_3 < 16U)
                    {
                    }
                    else
                    {

#line 496
                        break;
                    }

#line 497
                    uint j_1 = d_3 / _S23;

#line 497
                    uint m_0 = d_3 % _S23;
                    want_1[d_3] = _S19 * 64U + (lane_0 * _S24 + j_1) * 4U + m_0;

#line 496
                    d_3 = d_3 + 1U;

#line 496
                }

#line 496
                thread array<uint, int(16)> _S28 = want_1;

#line 496
                exchange_0(&r_4, &_S28, lgLn_0, lgTB_0, kernelContext_3);

#line 464
                break;
            }

#line 464
            break;
        }

#line 464
        break;
    }

#line 504
    innermost_0(&r_4);

#line 517
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 517
    uint b_6 = tid_0;

#line 525
    for(;;)
    {

#line 525
        if(b_6 < nbins_1)
        {
        }
        else
        {

#line 525
            break;
        }

#line 525
        (*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_6] = thrBits_1;

#line 525
        b_6 = b_6 + 4U;

#line 525
    }

    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;
    thread array<uint, int(16)> myBin_0;

#line 530
    uint i_5 = 0U;
    for(;;)
    {

#line 531
        if(i_5 < 16U)
        {
        }
        else
        {

#line 531
            break;
        }

#line 532
        uint idx_0 = slotToIndex_0(tid_0 * 16U + i_5);
        if(idx_0 >= winStart_1)
        {

#line 533
            live_0 = idx_0 < winEnd_1;

#line 533
        }
        else
        {

#line 533
            live_0 = false;

#line 533
        }



        float _rx_0 = r_4[i_5].x;

#line 537
        float _ry_0 = r_4[i_5].y;
        if(live_0)
        {

#line 538
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 538
        }
        else
        {

#line 538
            n2_0 = 0U;

#line 538
        }

#line 538
        myMag_0[i_5] = n2_0;
        uint off_0 = idx_0 - winStart_1;

#line 546
        if(live_0)
        {

#line 546
            if(binShift_1 >= int(0))
            {

#line 546
                z_1 = off_0 >> uint(binShift_1);

#line 546
            }
            else
            {

#line 546
                uint _S29 = off_0 / binsize_1;

#line 546
                z_1 = _S29;

#line 546
            }

#line 546
        }
        else
        {

#line 546
            z_1 = 0U;

#line 546
        }

#line 546
        myBin_0[i_5] = z_1;

#line 546
        bool _S30;



        if(nbins_1 > 1U)
        {

#line 550
            _S30 = (myMag_0[i_5]) > thrBits_1;

#line 550
        }
        else
        {

#line 550
            _S30 = false;

#line 550
        }

#line 550
        if(_S30)
        {

#line 551
            uint _S31 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_5]])), myMag_0[i_5], memory_order_relaxed);

#line 550
        }

#line 531
        i_5 = i_5 + 1U;

#line 531
    }

#line 563
    if(nbins_1 == 1U)
    {

#line 563
        i_5 = 0U;

#line 563
        uint bestBits_0 = thrBits_1;


        for(;;)
        {

#line 566
            if(i_5 < 16U)
            {
            }
            else
            {

#line 566
                break;
            }

#line 566
            uint _S32 = max(bestBits_0, myMag_0[i_5]);

#line 566
            i_5 = i_5 + 1U;

#line 566
            bestBits_0 = _S32;

#line 566
        }

        uint wm_0 = simd_max(bestBits_0);
        bool _S33 = simd_is_first();

#line 569
        if(_S33)
        {

#line 569
            live_0 = wm_0 > thrBits_1;

#line 569
        }
        else
        {

#line 569
            live_0 = false;

#line 569
        }

#line 569
        if(live_0)
        {

#line 569
            uint _S34 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0])), wm_0, memory_order_relaxed);

#line 569
        }

#line 563
    }

#line 584
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 584
    i_5 = 0U;

#line 589
    for(;;)
    {

#line 589
        if(i_5 < 16U)
        {
        }
        else
        {

#line 589
            break;
        }



        if((myMag_0[i_5]) > thrBits_1)
        {

#line 594
            live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_5]]) == myMag_0[i_5];

#line 594
        }
        else
        {

#line 594
            live_0 = false;

#line 594
        }

#line 594
        if(live_0)
        {

#line 595
            uint o_1 = pair_0 * nbins_1 + myBin_0[i_5];

            *(peakIdx_0+o_1) = int(slotToIndex_0(tid_0 * 16U + i_5));

#line 597
            *(peakVal_0+o_1) = packed_float2(float2(r_4[i_5].x, r_4[i_5].y)) ;

#line 594
        }

#line 589
        i_5 = i_5 + 1U;

#line 589
    }

#line 589
    b_6 = tid_0;

#line 608
    for(;;)
    {

#line 608
        if(b_6 < nbins_1)
        {
        }
        else
        {

#line 608
            break;
        }

#line 609
        if(((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_6]) == thrBits_1)
        {

#line 610
            uint o_2 = pair_0 * nbins_1 + b_6;

            *(peakIdx_0+o_2) = int(-1);

#line 612
            *(peakVal_0+o_2) = packed_float2(float2(0.0f, 0.0f)) ;

#line 609
        }

#line 608
        b_6 = b_6 + 4U;

#line 608
    }

#line 616
    return;
}


#line 741
void filterPair_0(uint pair_1, uint tid_1, packed_float2 device* data_0, packed_float2 device* tmpl_1, int device* peakIdx_1, packed_float2 device* peakVal_1, uint ntmpl_1, uint winStart_2, uint winEnd_2, uint binsize_2, int binShift_2, uint nbins_2, uint thrBits_2, KernelContext_0 thread* kernelContext_4)
{

#line 747
    kernelContext_4->_tid_0 = tid_1;

#line 757
    uint _S35 = pair_1 / ntmpl_1;

#line 757
    uint _S36 = pair_1 % ntmpl_1;
    thread array<float2, int(16)> dreg_1;

#line 758
    uint n2_1 = 0U;
    for(;;)
    {

#line 759
        if(n2_1 < 16U)
        {
        }
        else
        {

#line 759
            break;
        }

#line 760
        dreg_1[n2_1] = cload_0(data_0, _S35 * 64U + tid_1 + 4U * n2_1);

#line 759
        n2_1 = n2_1 + 1U;

#line 759
    }

#line 759
    uint k_0 = 0U;

#line 767
    for(;;)
    {

#line 767
        if(k_0 < 1U)
        {
        }
        else
        {

#line 767
            break;
        }

#line 768
        uint _S37 = pair_1 + k_0;

#line 768
        uint _S38 = _S36 + k_0;

#line 768
        thread array<float2, int(16)> _S39 = dreg_1;

#line 768
        filterOne_0(_S37, _S35, _S38, tid_1, &_S39, tmpl_1, peakIdx_1, peakVal_1, winStart_2, winEnd_2, binsize_2, binShift_2, nbins_2, thrBits_2, kernelContext_4);

#line 767
        k_0 = k_0 + 1U;

#line 767
    }



    return;
}

[[kernel]] void fusedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]])
{

#line 774
    thread KernelContext_0 kernelContext_5;

#line 774
    (&kernelContext_5)->entryPointParams_0 = entryPointParams_1;

#line 774
    (&kernelContext_5)->entryPointParams_data_0 = entryPointParams_data_1;

#line 774
    (&kernelContext_5)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 774
    (&kernelContext_5)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 774
    (&kernelContext_5)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 774
    threadgroup array<uint, int(128)> stg_1;

#line 774
    (&kernelContext_5)->stg_0 = &stg_1;

#line 791
    uint _pr_0 = gid_0.x;

#line 791
    uint _t_0 = lid_0.x;
    (&kernelContext_5)->_stgBase_0 = 0U;

#line 792
    filterPair_0(_pr_0, _t_0, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_5);

#line 800
    return;
}

