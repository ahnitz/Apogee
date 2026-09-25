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


#line 112 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_256_gatedTierB_c16.slang"
half2 cload_0(uint device* b_0, uint i_0)
{

#line 113
    uint p_0 = b_0[i_0];

#line 113
    return half2(half((as_type<half>((ushort)((p_0 & 65535U))))), half((as_type<half>((ushort)((p_0 >> 16U))))));
}


#line 156
half2 cmulConj_0(half2 a_0, half2 b_1)
{

#line 156
    half _S2 = a_0.x;

#line 156
    half _S3 = b_1.x;

#line 156
    half _S4 = a_0.y;

#line 156
    half _S5 = b_1.y;

#line 156
    return half2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 305
void r4_0(half2 thread* a_1, half2 thread* b_2, half2 thread* c_0, half2 thread* d_0)
{
    half2 t0_0 = *a_1 + *c_0;

#line 307
    half2 t1_0 = *a_1 - *c_0;

#line 307
    half2 t2_0 = *b_2 + *d_0;

#line 307
    half2 t3_0 = *b_2 - *d_0;
    half2 j3_0 = half2(- t3_0.y, t3_0.x);
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
half2 cmul_0(half2 a_2, half2 b_3)
{

#line 155
    half _S6 = a_2.x;

#line 155
    half _S7 = b_3.x;

#line 155
    half _S8 = a_2.y;

#line 155
    half _S9 = b_3.y;

#line 155
    return half2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 341
void dft16_0(array<half2, int(16)> thread* r_0)
{
    half2 W1_0 = half2(0.923828125h, 0.382568359375h);
    half2 W2_0 = half2(0.70703125h, 0.70703125h);
    half2 W3_0 = half2(0.382568359375h, 0.923828125h);
    half2 W4_0 = half2(0.0h, 1.0h);
    half2 W6_0 = half2(-0.70703125h, 0.70703125h);
    half2 W9_0 = half2(-0.923828125h, -0.382568359375h);

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

    half2 t_0 = (*r_0)[int(1)];

#line 355
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 355
    (*r_0)[int(4)] = t_0;
    half2 t_1 = (*r_0)[int(2)];

#line 356
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 356
    (*r_0)[int(8)] = t_1;
    half2 t_2 = (*r_0)[int(3)];

#line 357
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 357
    (*r_0)[int(12)] = t_2;
    half2 t_3 = (*r_0)[int(6)];

#line 358
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 358
    (*r_0)[int(9)] = t_3;
    half2 t_4 = (*r_0)[int(7)];

#line 359
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 359
    (*r_0)[int(13)] = t_4;
    half2 t_5 = (*r_0)[int(11)];

#line 360
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 360
    (*r_0)[int(14)] = t_5;
    return;
}


#line 341
void dft16_1(array<half2, int(16)> thread* r_1)
{
    half2 W1_1 = half2(0.923828125h, 0.382568359375h);
    half2 W2_1 = half2(0.70703125h, 0.70703125h);
    half2 W3_1 = half2(0.382568359375h, 0.923828125h);
    half2 W4_1 = half2(0.0h, 1.0h);
    half2 W6_1 = half2(-0.70703125h, 0.70703125h);
    half2 W9_1 = half2(-0.923828125h, -0.382568359375h);

#line 348
    uint n1_1 = 0U;
    for(;;)
    {

#line 349
        if(n1_1 < 4U)
        {
        }
        else
        {

#line 349
            break;
        }

#line 349
        r4_0(&(*r_1)[n1_1], &(*r_1)[n1_1 + 4U], &(*r_1)[n1_1 + 8U], &(*r_1)[n1_1 + 12U]);

#line 349
        n1_1 = n1_1 + 1U;

#line 349
    }
    (*r_1)[int(5)] = cmul_0((*r_1)[int(5)], W1_1);

#line 350
    (*r_1)[int(9)] = cmul_0((*r_1)[int(9)], W2_1);

#line 350
    (*r_1)[int(13)] = cmul_0((*r_1)[int(13)], W3_1);
    (*r_1)[int(6)] = cmul_0((*r_1)[int(6)], W2_1);

#line 351
    (*r_1)[int(10)] = cmul_0((*r_1)[int(10)], W4_1);

#line 351
    (*r_1)[int(14)] = cmul_0((*r_1)[int(14)], W6_1);
    (*r_1)[int(7)] = cmul_0((*r_1)[int(7)], W3_1);

#line 352
    (*r_1)[int(11)] = cmul_0((*r_1)[int(11)], W6_1);

#line 352
    (*r_1)[int(15)] = cmul_0((*r_1)[int(15)], W9_1);

#line 352
    uint k2_1 = 0U;
    for(;;)
    {

#line 353
        if(k2_1 < 4U)
        {
        }
        else
        {

#line 353
            break;
        }

#line 353
        uint _S11 = 4U * k2_1;

#line 353
        r4_0(&(*r_1)[_S11], &(*r_1)[_S11 + 1U], &(*r_1)[_S11 + 2U], &(*r_1)[_S11 + 3U]);

#line 353
        k2_1 = k2_1 + 1U;

#line 353
    }

    half2 t_6 = (*r_1)[int(1)];

#line 355
    (*r_1)[int(1)] = (*r_1)[int(4)];

#line 355
    (*r_1)[int(4)] = t_6;
    half2 t_7 = (*r_1)[int(2)];

#line 356
    (*r_1)[int(2)] = (*r_1)[int(8)];

#line 356
    (*r_1)[int(8)] = t_7;
    half2 t_8 = (*r_1)[int(3)];

#line 357
    (*r_1)[int(3)] = (*r_1)[int(12)];

#line 357
    (*r_1)[int(12)] = t_8;
    half2 t_9 = (*r_1)[int(6)];

#line 358
    (*r_1)[int(6)] = (*r_1)[int(9)];

#line 358
    (*r_1)[int(9)] = t_9;
    half2 t_10 = (*r_1)[int(7)];

#line 359
    (*r_1)[int(7)] = (*r_1)[int(13)];

#line 359
    (*r_1)[int(13)] = t_10;
    half2 t_11 = (*r_1)[int(11)];

#line 360
    (*r_1)[int(11)] = (*r_1)[int(14)];

#line 360
    (*r_1)[int(14)] = t_11;
    return;
}


#line 90 "core"
struct EntryPointParams_0
{
    uint ntmpl_0;
    uint winStart_0;
    uint winEnd_0;
    uint binsize_0;
    int binShift_0;
    uint nbins_0;
    uint thrBits_0;
    float thr_0;
};


#line 138 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_256_gatedTierB_c16.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    uint device* entryPointParams_data_0;
    uint device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    packed_float2 device* entryPointParams_coarse_0;
    uint _stgBase_0;
    uint _tid_0;
    array<uint, int(256)> threadgroup* stg_0;
};


#line 138
void stgPut_0(uint i_1, half2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 138
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + i_1] = (uint(as_type<ushort>(v_0[0U])) & 65535U) | (uint(as_type<ushort>(v_0[1U])) << 16U);

#line 138
    return;
}


#line 139
half2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 139
    return half2(as_type<half>(ushort(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + i_2]) & 65535U)), as_type<half>(ushort((((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + i_2]) >> 16U) & 65535U)));
}


#line 382
void exchange_0(array<half2, int(16)> thread* r_2, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 382
    uint j_0;

#line 393
    thread array<half2, int(16)> out_0;

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
        out_0[z_0] = half2(0.0h, 0.0h);

#line 394
        z_0 = z_0 + 1U;

#line 394
    }
    uint _S12 = (1U << lgSpan_0) - 1U;
    uint _S13 = (1U << lgLen_0) - 1U;

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
            stgPut_0(j_0 * 16U + kernelContext_2->_tid_0, (*r_2)[c_1 * 16U + j_0], kernelContext_2);

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
            uint rem_0 = ((*want_0)[d_1]) & _S13;
            uint i_3 = rem_0 >> lgSpan_0;

#line 404
            uint ln_0 = rem_0 & _S12;
            uint _S14 = c_1 * 16U;

#line 405
            bool _S15;

#line 405
            if(i_3 >= _S14)
            {

#line 405
                _S15 = i_3 < ((c_1 + 1U) * 16U);

#line 405
            }
            else
            {

#line 405
                _S15 = false;

#line 405
            }

#line 405
            if(_S15)
            {

#line 405
                half2 _S16 = stgGet_0((i_3 - _S14) * 16U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S16;

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
        (*r_2)[j_0] = out_0[j_0];

#line 409
        j_0 = j_0 + 1U;

#line 409
    }
    return;
}


#line 366
void innermost_0(array<half2, int(16)> thread* r_3)
{
    dft16_1(r_3);



    return;
}


#line 431
uint lgOf_0(uint i_4)
{

#line 431
    uint _S17;

#line 431
    if(i_4 < 1U)
    {

#line 431
        _S17 = 4U;

#line 431
    }
    else
    {

#line 431
        if(i_4 == 1U)
        {

#line 431
            _S17 = 4U;

#line 431
        }
        else
        {

#line 431
            _S17 = 1U;

#line 431
        }

#line 431
    }

#line 431
    return _S17;
}


#line 433
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(1U);

#line 437
    uint lg_1 = lgOf_0(0U);

#line 442
    return (((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | ((slot_0 >> lg_0) & ((1U << lg_1) - 1U));
}


#line 452
void filterOne_0(uint pair_0, uint d_2, uint t_12, uint tid_0, const array<half2, int(16)> thread* dreg_0, uint device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{


    bool live_0;

    thread array<half2, int(16)> r_4;

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
        r_4[n2_0] = cmulConj_0((*dreg_0)[n2_0], cload_0(tmpl_0, t_12 * 256U + tid_0 + 16U * n2_0));

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
                uint z_1 = 0U;
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



                uint lgTB_0 = firstbithigh_0(16U);
                uint lgLn_0 = firstbithigh_0(256U);
                uint _S18 = tid_0 >> lgTB_0;
                uint _S19 = tid_0 & 15U;

                dft16_0(&r_4);

#line 475
                uint k2_2 = 0U;
                for(;;)
                {

#line 476
                    if(k2_2 < 16U)
                    {
                    }
                    else
                    {

#line 476
                        break;
                    }

#line 477
                    float ang_0 = 6.28318548202514648f * float(_S19 * k2_2) / 256.0f;
                    r_4[k2_2] = cmul_0(r_4[k2_2], half2(half(cos(ang_0)), half(sin(ang_0))));

#line 476
                    k2_2 = k2_2 + 1U;

#line 476
                }

#line 483
                uint _S20 = max(16U, 1U);

#line 483
                uint _S21 = 16U / _S20;
                uint _S22 = max(1U, 1U);
                uint _S23 = tid_0 / _S22;

#line 485
                uint _S24 = tid_0 % _S22;

#line 485
                uint d_3 = 0U;
                for(;;)
                {

#line 486
                    if(d_3 < 16U)
                    {
                    }
                    else
                    {

#line 486
                        break;
                    }

#line 487
                    uint j_1 = d_3 / _S20;

#line 487
                    uint m_0 = d_3 % _S20;
                    want_1[d_3] = _S18 * 256U + (_S19 * _S21 + j_1) * 16U + m_0;

#line 486
                    d_3 = d_3 + 1U;

#line 486
                }

#line 486
                thread array<uint, int(16)> _S25 = want_1;

#line 486
                exchange_0(&r_4, &_S25, lgLn_0, lgTB_0, kernelContext_3);

#line 464
                break;
            }

#line 464
            break;
        }

#line 464
        break;
    }

#line 494
    innermost_0(&r_4);

#line 507
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 513
    bool _S26 = tid_0 == 0U;

#line 513
    if(_S26)
    {

#line 513
        (*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0] = thrBits_1;

#line 513
    }



    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;

#line 519
    uint i_5 = 0U;

    for(;;)
    {

#line 521
        if(i_5 < 16U)
        {
        }
        else
        {

#line 521
            break;
        }

#line 522
        uint idx_0 = slotToIndex_0(tid_0 * 16U + i_5);
        if(idx_0 >= winStart_1)
        {

#line 523
            live_0 = idx_0 < winEnd_1;

#line 523
        }
        else
        {

#line 523
            live_0 = false;

#line 523
        }



        float _rx_0 = float(r_4[i_5].x);

#line 527
        float _ry_0 = float(r_4[i_5].y);
        if(live_0)
        {

#line 528
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 528
        }
        else
        {

#line 528
            n2_0 = 0U;

#line 528
        }

#line 528
        myMag_0[i_5] = n2_0;

#line 521
        i_5 = i_5 + 1U;

#line 521
    }

#line 521
    i_5 = 0U;

#line 521
    uint bestBits_0 = thrBits_1;

#line 556
    for(;;)
    {

#line 556
        if(i_5 < 16U)
        {
        }
        else
        {

#line 556
            break;
        }

#line 556
        uint _S27 = max(bestBits_0, myMag_0[i_5]);

#line 556
        i_5 = i_5 + 1U;

#line 556
        bestBits_0 = _S27;

#line 556
    }

    uint wm_0 = simd_max(bestBits_0);
    bool _S28 = simd_is_first();

#line 559
    if(_S28)
    {

#line 559
        live_0 = wm_0 > thrBits_1;

#line 559
    }
    else
    {

#line 559
        live_0 = false;

#line 559
    }

#line 559
    if(live_0)
    {

#line 559
        uint _S29 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0])), wm_0, memory_order_relaxed);

#line 559
    }

#line 574
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 574
    i_5 = 0U;

#line 579
    for(;;)
    {

#line 579
        if(i_5 < 16U)
        {
        }
        else
        {

#line 579
            break;
        }
        if((myMag_0[i_5]) > thrBits_1)
        {

#line 581
            live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0]) == myMag_0[i_5];

#line 581
        }
        else
        {

#line 581
            live_0 = false;

#line 581
        }

#line 581
        if(live_0)
        {

#line 587
            *(peakIdx_0+pair_0) = int(slotToIndex_0(tid_0 * 16U + i_5));

#line 587
            *(peakVal_0+pair_0) = packed_float2(float2(float(r_4[i_5].x), float(r_4[i_5].y))) ;

#line 581
        }

#line 579
        i_5 = i_5 + 1U;

#line 579
    }

#line 594
    if(_S26)
    {

#line 594
        live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0]) == thrBits_1;

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

#line 602
        *(peakIdx_0+pair_0) = int(-1);

#line 602
        *(peakVal_0+pair_0) = packed_float2(float2(0.0f, 0.0f)) ;

#line 594
    }

#line 606
    return;
}


#line 716
void filterPair_0(uint pair_1, uint tid_1, uint device* data_0, uint device* tmpl_1, int device* peakIdx_1, packed_float2 device* peakVal_1, uint ntmpl_1, uint winStart_2, uint winEnd_2, uint binsize_2, int binShift_2, uint nbins_2, uint thrBits_2, KernelContext_0 thread* kernelContext_4)
{

#line 722
    kernelContext_4->_tid_0 = tid_1;

#line 732
    uint _S30 = pair_1 / ntmpl_1;

#line 732
    uint _S31 = pair_1 % ntmpl_1;
    thread array<half2, int(16)> dreg_1;

#line 733
    uint n2_1 = 0U;
    for(;;)
    {

#line 734
        if(n2_1 < 16U)
        {
        }
        else
        {

#line 734
            break;
        }

#line 735
        dreg_1[n2_1] = cload_0(data_0, _S30 * 256U + tid_1 + 16U * n2_1);

#line 734
        n2_1 = n2_1 + 1U;

#line 734
    }

#line 734
    uint k_0 = 0U;

#line 742
    for(;;)
    {

#line 742
        if(k_0 < 1U)
        {
        }
        else
        {

#line 742
            break;
        }

#line 743
        uint _S32 = pair_1 + k_0;

#line 743
        uint _S33 = _S31 + k_0;

#line 743
        thread array<half2, int(16)> _S34 = dreg_1;

#line 743
        filterOne_0(_S32, _S30, _S33, tid_1, &_S34, tmpl_1, peakIdx_1, peakVal_1, winStart_2, winEnd_2, binsize_2, binShift_2, nbins_2, thrBits_2, kernelContext_4);

#line 742
        k_0 = k_0 + 1U;

#line 742
    }



    return;
}


#line 790
[[kernel]] void gatedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], uint device* entryPointParams_data_1 [[buffer(1)]], uint device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]], packed_float2 device* entryPointParams_coarse_1 [[buffer(5)]])
{

#line 790
    thread KernelContext_0 kernelContext_5;

#line 790
    (&kernelContext_5)->entryPointParams_0 = entryPointParams_1;

#line 790
    (&kernelContext_5)->entryPointParams_data_0 = entryPointParams_data_1;

#line 790
    (&kernelContext_5)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 790
    (&kernelContext_5)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 790
    (&kernelContext_5)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 790
    (&kernelContext_5)->entryPointParams_coarse_0 = entryPointParams_coarse_1;

#line 790
    threadgroup array<uint, int(256)> stg_1;

#line 790
    (&kernelContext_5)->stg_0 = &stg_1;

#line 800
    uint pair_2 = gid_0.x;

#line 800
    uint tid_2 = lid_0.x;
    (&kernelContext_5)->_stgBase_0 = 0U;

#line 813
    if((length(float2(*(entryPointParams_coarse_1+pair_2)) )) < (entryPointParams_1->thr_0))
    {

#line 813
        uint b_5 = tid_2;
        for(;;)
        {

#line 814
            if(b_5 < ((&kernelContext_5)->entryPointParams_0->nbins_0))
            {
            }
            else
            {

#line 814
                break;
            }

#line 815
            uint o_0 = pair_2 * (&kernelContext_5)->entryPointParams_0->nbins_0 + b_5;
            *((&kernelContext_5)->entryPointParams_peakIdx_0+o_0) = int(-1);

#line 816
            *((&kernelContext_5)->entryPointParams_peakVal_0+o_0) = packed_float2(float2(0.0f, 0.0f)) ;

#line 814
            b_5 = b_5 + 16U;

#line 814
        }

#line 819
        return;
    }

#line 819
    filterPair_0(pair_2, tid_2, (&kernelContext_5)->entryPointParams_data_0, (&kernelContext_5)->entryPointParams_tmpl_0, (&kernelContext_5)->entryPointParams_peakIdx_0, (&kernelContext_5)->entryPointParams_peakVal_0, (&kernelContext_5)->entryPointParams_0->ntmpl_0, (&kernelContext_5)->entryPointParams_0->winStart_0, (&kernelContext_5)->entryPointParams_0->winEnd_0, (&kernelContext_5)->entryPointParams_0->binsize_0, (&kernelContext_5)->entryPointParams_0->binShift_0, (&kernelContext_5)->entryPointParams_0->nbins_0, (&kernelContext_5)->entryPointParams_0->thrBits_0, &kernelContext_5);



    return;
}

