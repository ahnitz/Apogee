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


#line 112 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_128_fusedTierB_c16.slang"
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
};


#line 138 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_128_fusedTierB_c16.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    uint device* entryPointParams_data_0;
    uint device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    uint _stgBase_0;
    uint _tid_0;
    array<uint, int(128)> threadgroup* stg_0;
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
void exchange_0(array<half2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
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
    uint _S11 = (1U << lgSpan_0) - 1U;
    uint _S12 = (1U << lgLen_0) - 1U;

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
            stgPut_0(j_0 * 8U + kernelContext_2->_tid_0, (*r_1)[c_1 * 16U + j_0], kernelContext_2);

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
            uint rem_0 = ((*want_0)[d_1]) & _S12;
            uint i_3 = rem_0 >> lgSpan_0;

#line 404
            uint ln_0 = rem_0 & _S11;
            uint _S13 = c_1 * 16U;

#line 405
            bool _S14;

#line 405
            if(i_3 >= _S13)
            {

#line 405
                _S14 = i_3 < ((c_1 + 1U) * 16U);

#line 405
            }
            else
            {

#line 405
                _S14 = false;

#line 405
            }

#line 405
            if(_S14)
            {

#line 405
                half2 _S15 = stgGet_0((i_3 - _S13) * 8U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S15;

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
void dft8_0(array<half2, int(16)> thread* r_2, uint o_0)
{


    thread array<half2, int(8)> b_5;

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

            uint _S16 = o_0 + j_1;

#line 335
            half2 t_6 = cmul_0(half2(half(cos(ang_0)), half(sin(ang_0))), (*r_2)[_S16 + 4U]);
            uint _S17 = ((j_1 - k_0) << 1U) + k_0;

#line 336
            b_5[_S17] = (*r_2)[_S16] + t_6;

#line 336
            b_5[_S17 + s_0] = (*r_2)[_S16] - t_6;

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
void innermost_0(array<half2, int(16)> thread* r_3)
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
    uint _S18;

#line 431
    if(i_5 < 1U)
    {

#line 431
        _S18 = 4U;

#line 431
    }
    else
    {

#line 431
        if(i_5 == 1U)
        {

#line 431
            _S18 = 3U;

#line 431
        }
        else
        {

#line 431
            _S18 = 1U;

#line 431
        }

#line 431
    }

#line 431
    return _S18;
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
void filterOne_0(uint pair_0, uint d_2, uint t_7, uint tid_0, const array<half2, int(16)> thread* dreg_0, uint device* data_0, uint device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{


    bool live_0;

    thread array<half2, int(16)> r_4;

#line 458
    uint n2_0 = 0U;



    for(;;)
    {

#line 462
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 462
            break;
        }

#line 463
        r_4[n2_0] = cmulConj_0((*dreg_0)[n2_0], cload_0(tmpl_0, t_7 * 128U + tid_0 + 8U * n2_0));

#line 462
        n2_0 = n2_0 + 1U;

#line 462
    }

#line 462
    for(;;)
    {

#line 462
        for(;;)
        {

#line 475
            for(;;)
            {

#line 476
                thread array<uint, int(16)> want_1;

#line 476
                uint z_1 = 0U;
                for(;;)
                {

#line 477
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 477
                        break;
                    }

#line 477
                    want_1[z_1] = 0U;

#line 477
                    z_1 = z_1 + 1U;

#line 477
                }



                uint lgTB_0 = firstbithigh_0(8U);
                uint lgLn_0 = firstbithigh_0(128U);
                uint _S19 = tid_0 >> lgTB_0;
                uint lane_0 = tid_0 & 7U;

                dft16_0(&r_4);

#line 491
                float a1_0 = 6.28318548202514648f * float(lane_0) / 128.0f;
                float _S20 = cos(a1_0);

#line 492
                float _S21 = sin(a1_0);

#line 492
                uint k2_1 = 0U;

#line 492
                float cr_0 = 1.0f;

#line 492
                float ci_0 = 0.0f;

                for(;;)
                {

#line 494
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 494
                        break;
                    }

#line 495
                    r_4[k2_1] = cmul_0(r_4[k2_1], half2(half(cr_0), half(ci_0)));
                    float nr_0 = cr_0 * _S20 - ci_0 * _S21;
                    float _S22 = cr_0 * _S21 + ci_0 * _S20;

#line 494
                    k2_1 = k2_1 + 1U;

#line 494
                    cr_0 = nr_0;

#line 494
                    ci_0 = _S22;

#line 494
                }

#line 504
                uint _S23 = max(8U, 1U);

#line 504
                uint _S24 = 16U / _S23;
                uint _S25 = max(0U, 1U);
                uint _S26 = tid_0 / _S25;

#line 506
                uint _S27 = tid_0 % _S25;

#line 506
                uint d_3 = 0U;
                for(;;)
                {

#line 507
                    if(d_3 < 16U)
                    {
                    }
                    else
                    {

#line 507
                        break;
                    }

#line 508
                    uint j_2 = d_3 / _S23;

#line 508
                    uint m_0 = d_3 % _S23;
                    want_1[d_3] = _S19 * 128U + (lane_0 * _S24 + j_2) * 8U + m_0;

#line 507
                    d_3 = d_3 + 1U;

#line 507
                }

#line 507
                thread array<uint, int(16)> _S28 = want_1;

#line 507
                exchange_0(&r_4, &_S28, lgLn_0, lgTB_0, kernelContext_3);

#line 475
                break;
            }

#line 475
            break;
        }

#line 475
        break;
    }

#line 515
    innermost_0(&r_4);

#line 528
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 534
    bool _S29 = tid_0 == 0U;

#line 534
    if(_S29)
    {

#line 534
        (*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0] = thrBits_1;

#line 534
    }



    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;

#line 540
    uint i_6 = 0U;

    for(;;)
    {

#line 542
        if(i_6 < 16U)
        {
        }
        else
        {

#line 542
            break;
        }

#line 543
        uint idx_0 = slotToIndex_0(tid_0 * 16U + i_6);
        if(idx_0 >= winStart_1)
        {

#line 544
            live_0 = idx_0 < winEnd_1;

#line 544
        }
        else
        {

#line 544
            live_0 = false;

#line 544
        }



        float _rx_0 = float(r_4[i_6].x);

#line 548
        float _ry_0 = float(r_4[i_6].y);
        if(live_0)
        {

#line 549
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 549
        }
        else
        {

#line 549
            n2_0 = 0U;

#line 549
        }

#line 549
        myMag_0[i_6] = n2_0;

#line 542
        i_6 = i_6 + 1U;

#line 542
    }

#line 542
    i_6 = 0U;

#line 542
    uint bestBits_0 = thrBits_1;

#line 577
    for(;;)
    {

#line 577
        if(i_6 < 16U)
        {
        }
        else
        {

#line 577
            break;
        }

#line 577
        uint _S30 = max(bestBits_0, myMag_0[i_6]);

#line 577
        i_6 = i_6 + 1U;

#line 577
        bestBits_0 = _S30;

#line 577
    }

    uint wm_0 = simd_max(bestBits_0);
    bool _S31 = simd_is_first();

#line 580
    if(_S31)
    {

#line 580
        live_0 = wm_0 > thrBits_1;

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

#line 580
        uint _S32 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0])), wm_0, memory_order_relaxed);

#line 580
    }

#line 595
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 595
    i_6 = 0U;

#line 600
    for(;;)
    {

#line 600
        if(i_6 < 16U)
        {
        }
        else
        {

#line 600
            break;
        }
        if((myMag_0[i_6]) > thrBits_1)
        {

#line 602
            live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0]) == myMag_0[i_6];

#line 602
        }
        else
        {

#line 602
            live_0 = false;

#line 602
        }

#line 602
        if(live_0)
        {

#line 608
            *(peakIdx_0+pair_0) = int(slotToIndex_0(tid_0 * 16U + i_6));

#line 608
            *(peakVal_0+pair_0) = packed_float2(float2(float(r_4[i_6].x), float(r_4[i_6].y))) ;

#line 602
        }

#line 600
        i_6 = i_6 + 1U;

#line 600
    }

#line 615
    if(_S29)
    {

#line 615
        live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0]) == thrBits_1;

#line 615
    }
    else
    {

#line 615
        live_0 = false;

#line 615
    }

#line 615
    if(live_0)
    {

#line 623
        *(peakIdx_0+pair_0) = int(-1);

#line 623
        *(peakVal_0+pair_0) = packed_float2(float2(0.0f, 0.0f)) ;

#line 615
    }

#line 627
    return;
}


#line 752
void filterPair_0(uint pair_1, uint tid_1, uint device* data_1, uint device* tmpl_1, int device* peakIdx_1, packed_float2 device* peakVal_1, uint ntmpl_1, uint winStart_2, uint winEnd_2, uint binsize_2, int binShift_2, uint nbins_2, uint thrBits_2, KernelContext_0 thread* kernelContext_4)
{

#line 758
    kernelContext_4->_tid_0 = tid_1;

#line 768
    uint _S33 = pair_1 / ntmpl_1;

#line 768
    uint _S34 = pair_1 % ntmpl_1;
    thread array<half2, int(16)> dreg_1;

#line 769
    uint n2_1 = 0U;

    for(;;)
    {

#line 771
        if(n2_1 < 16U)
        {
        }
        else
        {

#line 771
            break;
        }

#line 772
        dreg_1[n2_1] = cload_0(data_1, _S33 * 128U + tid_1 + 8U * n2_1);

#line 771
        n2_1 = n2_1 + 1U;

#line 771
    }

#line 771
    uint k_1 = 0U;

#line 782
    for(;;)
    {

#line 782
        if(k_1 < 1U)
        {
        }
        else
        {

#line 782
            break;
        }

#line 783
        uint _S35 = pair_1 + k_1;

#line 783
        uint _S36 = _S34 + k_1;

#line 783
        thread array<half2, int(16)> _S37 = dreg_1;

#line 783
        filterOne_0(_S35, _S33, _S36, tid_1, &_S37, data_1, tmpl_1, peakIdx_1, peakVal_1, winStart_2, winEnd_2, binsize_2, binShift_2, nbins_2, thrBits_2, kernelContext_4);

#line 782
        k_1 = k_1 + 1U;

#line 782
    }



    return;
}

[[kernel]] void fusedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], uint device* entryPointParams_data_1 [[buffer(1)]], uint device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]])
{

#line 789
    thread KernelContext_0 kernelContext_5;

#line 789
    (&kernelContext_5)->entryPointParams_0 = entryPointParams_1;

#line 789
    (&kernelContext_5)->entryPointParams_data_0 = entryPointParams_data_1;

#line 789
    (&kernelContext_5)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 789
    (&kernelContext_5)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 789
    (&kernelContext_5)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 789
    threadgroup array<uint, int(128)> stg_1;

#line 789
    (&kernelContext_5)->stg_0 = &stg_1;

#line 806
    uint _pr_0 = gid_0.x;

#line 806
    uint _t_0 = lid_0.x;
    (&kernelContext_5)->_stgBase_0 = 0U;

#line 807
    filterPair_0(_pr_0, _t_0, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_5);

#line 815
    return;
}

