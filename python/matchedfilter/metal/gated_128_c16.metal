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


#line 112 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_128_gatedTierB_c16.slang"
half2 cload_0(uint device* b_0, uint i_0)
{

#line 113
    uint p_0 = b_0[i_0];

#line 113
    return half2(half((as_type<half>((ushort)((p_0 & 65535U))))), half((as_type<half>((ushort)((p_0 >> 16U))))));
}


#line 152
half2 cmulConj_0(half2 a_0, half2 b_1)
{

#line 152
    half _S2 = a_0.x;

#line 152
    half _S3 = b_1.x;

#line 152
    half _S4 = a_0.y;

#line 152
    half _S5 = b_1.y;

#line 152
    return half2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 301
void r4_0(half2 thread* a_1, half2 thread* b_2, half2 thread* c_0, half2 thread* d_0)
{
    half2 t0_0 = *a_1 + *c_0;

#line 303
    half2 t1_0 = *a_1 - *c_0;

#line 303
    half2 t2_0 = *b_2 + *d_0;

#line 303
    half2 t3_0 = *b_2 - *d_0;
    half2 j3_0 = half2(- t3_0.y, t3_0.x);
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
half2 cmul_0(half2 a_2, half2 b_3)
{

#line 151
    half _S6 = a_2.x;

#line 151
    half _S7 = b_3.x;

#line 151
    half _S8 = a_2.y;

#line 151
    half _S9 = b_3.y;

#line 151
    return half2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 337
void dft16_0(array<half2, int(16)> thread* r_0)
{
    half2 W1_0 = half2(0.923828125h, 0.382568359375h);
    half2 W2_0 = half2(0.70703125h, 0.70703125h);
    half2 W3_0 = half2(0.382568359375h, 0.923828125h);
    half2 W4_0 = half2(0.0h, 1.0h);
    half2 W6_0 = half2(-0.70703125h, 0.70703125h);
    half2 W9_0 = half2(-0.923828125h, -0.382568359375h);

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

    half2 t_0 = (*r_0)[int(1)];

#line 351
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 351
    (*r_0)[int(4)] = t_0;
    half2 t_1 = (*r_0)[int(2)];

#line 352
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 352
    (*r_0)[int(8)] = t_1;
    half2 t_2 = (*r_0)[int(3)];

#line 353
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 353
    (*r_0)[int(12)] = t_2;
    half2 t_3 = (*r_0)[int(6)];

#line 354
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 354
    (*r_0)[int(9)] = t_3;
    half2 t_4 = (*r_0)[int(7)];

#line 355
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 355
    (*r_0)[int(13)] = t_4;
    half2 t_5 = (*r_0)[int(11)];

#line 356
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 356
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
    float thr_0;
};


#line 133 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_128_gatedTierB_c16.slang"
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
    array<uint, int(128)> threadgroup* stg_0;
};


#line 132
void stgPut_0(uint i_1, half2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 133
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + i_1] = ((as_type<ushort>((half)((float(v_0.x))))) & 65535U) | ((as_type<ushort>((half)((float(v_0.y))))) << 16U);

#line 133
    return;
}


#line 134
half2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 135
    return half2(half((as_type<half>((ushort)((((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + i_2]) & 65535U))))), half((as_type<half>((ushort)((((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + i_2]) >> 16U))))));
}


#line 378
void exchange_0(array<half2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 378
    uint j_0;

#line 389
    thread array<half2, int(16)> out_0;

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
        out_0[z_0] = half2(0.0h, 0.0h);

#line 390
        z_0 = z_0 + 1U;

#line 390
    }
    uint _S11 = (1U << lgSpan_0) - 1U;
    uint _S12 = (1U << lgLen_0) - 1U;

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
            stgPut_0(j_0 * 8U + kernelContext_2->_tid_0, (*r_1)[c_1 * 16U + j_0], kernelContext_2);

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
            uint rem_0 = ((*want_0)[d_1]) & _S12;
            uint i_3 = rem_0 >> lgSpan_0;

#line 400
            uint ln_0 = rem_0 & _S11;
            uint _S13 = c_1 * 16U;

#line 401
            bool _S14;

#line 401
            if(i_3 >= _S13)
            {

#line 401
                _S14 = i_3 < ((c_1 + 1U) * 16U);

#line 401
            }
            else
            {

#line 401
                _S14 = false;

#line 401
            }

#line 401
            if(_S14)
            {

#line 401
                half2 _S15 = stgGet_0((i_3 - _S13) * 8U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S15;

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


#line 321
void dft8_0(array<half2, int(16)> thread* r_2, uint o_0)
{


    thread array<half2, int(8)> b_5;

#line 325
    uint s_0 = 1U;
    for(;;)
    {

#line 326
        if(s_0 < 8U)
        {
        }
        else
        {

#line 326
            break;
        }

#line 326
        uint j_1 = 0U;
        for(;;)
        {

#line 327
            if(j_1 < 4U)
            {
            }
            else
            {

#line 327
                break;
            }

#line 328
            uint k_0 = j_1 & (s_0 - 1U);
            float ang_0 = 3.14159274101257324f * float(k_0) / float(s_0);

            uint _S16 = o_0 + j_1;

#line 331
            half2 t_6 = cmul_0(half2(half(cos(ang_0)), half(sin(ang_0))), (*r_2)[_S16 + 4U]);
            uint _S17 = ((j_1 - k_0) << 1U) + k_0;

#line 332
            b_5[_S17] = (*r_2)[_S16] + t_6;

#line 332
            b_5[_S17 + s_0] = (*r_2)[_S16] - t_6;

#line 327
            j_1 = j_1 + 1U;

#line 327
        }

#line 327
        uint i_4 = 0U;

#line 334
        for(;;)
        {

#line 334
            if(i_4 < 8U)
            {
            }
            else
            {

#line 334
                break;
            }

#line 334
            (*r_2)[o_0 + i_4] = b_5[i_4];

#line 334
            i_4 = i_4 + 1U;

#line 334
        }

#line 326
        s_0 = s_0 << 1U;

#line 326
    }

#line 336
    return;
}


#line 362
void innermost_0(array<half2, int(16)> thread* r_3)
{

#line 362
    uint b_6 = 0U;


    for(;;)
    {

#line 365
        if(b_6 < 2U)
        {
        }
        else
        {

#line 365
            break;
        }

#line 365
        dft8_0(r_3, b_6 * 8U);

#line 365
        b_6 = b_6 + 1U;

#line 365
    }


    return;
}


#line 427
uint lgOf_0(uint i_5)
{

#line 427
    uint _S18;

#line 427
    if(i_5 < 1U)
    {

#line 427
        _S18 = 4U;

#line 427
    }
    else
    {

#line 427
        if(i_5 == 1U)
        {

#line 427
            _S18 = 3U;

#line 427
        }
        else
        {

#line 427
            _S18 = 1U;

#line 427
        }

#line 427
    }

#line 427
    return _S18;
}


#line 429
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(1U);

#line 433
    uint lg_1 = lgOf_0(0U);

#line 438
    return (((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | ((slot_0 >> lg_0) & ((1U << lg_1) - 1U));
}


#line 448
void filterOne_0(uint pair_0, uint d_2, uint t_7, uint tid_0, const array<half2, int(16)> thread* dreg_0, uint device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{


    bool live_0;

    thread array<half2, int(16)> r_4;

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
        r_4[n2_0] = cmulConj_0((*dreg_0)[n2_0], cload_0(tmpl_0, t_7 * 128U + tid_0 + 8U * n2_0));

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
                uint z_1 = 0U;
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



                uint lgTB_0 = firstbithigh_0(8U);
                uint lgLn_0 = firstbithigh_0(128U);
                uint _S19 = tid_0 >> lgTB_0;
                uint _S20 = tid_0 & 7U;

                dft16_0(&r_4);

#line 471
                uint k2_1 = 0U;
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
                    float ang_1 = 6.28318548202514648f * float(_S20 * k2_1) / 128.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], half2(half(cos(ang_1)), half(sin(ang_1))));

#line 472
                    k2_1 = k2_1 + 1U;

#line 472
                }

#line 479
                uint _S21 = max(8U, 1U);

#line 479
                uint _S22 = 16U / _S21;
                uint _S23 = max(0U, 1U);
                uint _S24 = tid_0 / _S23;

#line 481
                uint _S25 = tid_0 % _S23;

#line 481
                uint d_3 = 0U;
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
                    uint j_2 = d_3 / _S21;

#line 483
                    uint m_0 = d_3 % _S21;
                    want_1[d_3] = _S19 * 128U + (_S20 * _S22 + j_2) * 8U + m_0;

#line 482
                    d_3 = d_3 + 1U;

#line 482
                }

#line 482
                thread array<uint, int(16)> _S26 = want_1;

#line 482
                exchange_0(&r_4, &_S26, lgLn_0, lgTB_0, kernelContext_3);

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

#line 509
    bool _S27 = tid_0 == 0U;

#line 509
    if(_S27)
    {

#line 509
        (*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0] = thrBits_1;

#line 509
    }



    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;

#line 515
    uint i_6 = 0U;

    for(;;)
    {

#line 517
        if(i_6 < 16U)
        {
        }
        else
        {

#line 517
            break;
        }

#line 518
        uint idx_0 = slotToIndex_0(tid_0 * 16U + i_6);
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



        float _rx_0 = float(r_4[i_6].x);

#line 523
        float _ry_0 = float(r_4[i_6].y);
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
        myMag_0[i_6] = n2_0;

#line 517
        i_6 = i_6 + 1U;

#line 517
    }

#line 517
    i_6 = 0U;

#line 517
    uint bestBits_0 = thrBits_1;

#line 552
    for(;;)
    {

#line 552
        if(i_6 < 16U)
        {
        }
        else
        {

#line 552
            break;
        }

#line 552
        uint _S28 = max(bestBits_0, myMag_0[i_6]);

#line 552
        i_6 = i_6 + 1U;

#line 552
        bestBits_0 = _S28;

#line 552
    }

    uint wm_0 = simd_max(bestBits_0);
    bool _S29 = simd_is_first();

#line 555
    if(_S29)
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
        uint _S30 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0])), wm_0, memory_order_relaxed);

#line 555
    }

#line 570
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 570
    i_6 = 0U;

#line 575
    for(;;)
    {

#line 575
        if(i_6 < 16U)
        {
        }
        else
        {

#line 575
            break;
        }
        if((myMag_0[i_6]) > thrBits_1)
        {

#line 577
            live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0]) == myMag_0[i_6];

#line 577
        }
        else
        {

#line 577
            live_0 = false;

#line 577
        }

#line 577
        if(live_0)
        {

#line 583
            *(peakIdx_0+pair_0) = int(slotToIndex_0(tid_0 * 16U + i_6));

#line 583
            *(peakVal_0+pair_0) = packed_float2(float2(float(r_4[i_6].x), float(r_4[i_6].y))) ;

#line 577
        }

#line 575
        i_6 = i_6 + 1U;

#line 575
    }

#line 590
    if(_S27)
    {

#line 590
        live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0]) == thrBits_1;

#line 590
    }
    else
    {

#line 590
        live_0 = false;

#line 590
    }

#line 590
    if(live_0)
    {

#line 598
        *(peakIdx_0+pair_0) = int(-1);

#line 598
        *(peakVal_0+pair_0) = packed_float2(float2(0.0f, 0.0f)) ;

#line 590
    }

#line 602
    return;
}


#line 707
void filterPair_0(uint pair_1, uint tid_1, uint device* data_0, uint device* tmpl_1, int device* peakIdx_1, packed_float2 device* peakVal_1, uint ntmpl_1, uint winStart_2, uint winEnd_2, uint binsize_2, int binShift_2, uint nbins_2, uint thrBits_2, KernelContext_0 thread* kernelContext_4)
{

#line 713
    kernelContext_4->_tid_0 = tid_1;

#line 723
    uint _S31 = pair_1 / ntmpl_1;

#line 723
    uint _S32 = pair_1 % ntmpl_1;
    thread array<half2, int(16)> dreg_1;

#line 724
    uint n2_1 = 0U;
    for(;;)
    {

#line 725
        if(n2_1 < 16U)
        {
        }
        else
        {

#line 725
            break;
        }

#line 726
        dreg_1[n2_1] = cload_0(data_0, _S31 * 128U + tid_1 + 8U * n2_1);

#line 725
        n2_1 = n2_1 + 1U;

#line 725
    }

#line 725
    uint k_1 = 0U;

#line 733
    for(;;)
    {

#line 733
        if(k_1 < 1U)
        {
        }
        else
        {

#line 733
            break;
        }

#line 734
        uint _S33 = pair_1 + k_1;

#line 734
        uint _S34 = _S32 + k_1;

#line 734
        thread array<half2, int(16)> _S35 = dreg_1;

#line 734
        filterOne_0(_S33, _S31, _S34, tid_1, &_S35, tmpl_1, peakIdx_1, peakVal_1, winStart_2, winEnd_2, binsize_2, binShift_2, nbins_2, thrBits_2, kernelContext_4);

#line 733
        k_1 = k_1 + 1U;

#line 733
    }



    return;
}


#line 781
[[kernel]] void gatedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], uint device* entryPointParams_data_1 [[buffer(1)]], uint device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]], packed_float2 device* entryPointParams_coarse_1 [[buffer(5)]])
{

#line 781
    thread KernelContext_0 kernelContext_5;

#line 781
    (&kernelContext_5)->entryPointParams_0 = entryPointParams_1;

#line 781
    (&kernelContext_5)->entryPointParams_data_0 = entryPointParams_data_1;

#line 781
    (&kernelContext_5)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 781
    (&kernelContext_5)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 781
    (&kernelContext_5)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 781
    (&kernelContext_5)->entryPointParams_coarse_0 = entryPointParams_coarse_1;

#line 781
    threadgroup array<uint, int(128)> stg_1;

#line 781
    (&kernelContext_5)->stg_0 = &stg_1;

#line 791
    uint pair_2 = gid_0.x;

#line 791
    uint tid_2 = lid_0.x;
    (&kernelContext_5)->_stgBase_0 = 0U;

#line 804
    if((length(float2(*(entryPointParams_coarse_1+pair_2)) )) < (entryPointParams_1->thr_0))
    {

#line 804
        uint b_7 = tid_2;
        for(;;)
        {

#line 805
            if(b_7 < ((&kernelContext_5)->entryPointParams_0->nbins_0))
            {
            }
            else
            {

#line 805
                break;
            }

#line 806
            uint o_1 = pair_2 * (&kernelContext_5)->entryPointParams_0->nbins_0 + b_7;
            *((&kernelContext_5)->entryPointParams_peakIdx_0+o_1) = int(-1);

#line 807
            *((&kernelContext_5)->entryPointParams_peakVal_0+o_1) = packed_float2(float2(0.0f, 0.0f)) ;

#line 805
            b_7 = b_7 + 8U;

#line 805
        }

#line 810
        return;
    }

#line 810
    filterPair_0(pair_2, tid_2, (&kernelContext_5)->entryPointParams_data_0, (&kernelContext_5)->entryPointParams_tmpl_0, (&kernelContext_5)->entryPointParams_peakIdx_0, (&kernelContext_5)->entryPointParams_peakVal_0, (&kernelContext_5)->entryPointParams_0->ntmpl_0, (&kernelContext_5)->entryPointParams_0->winStart_0, (&kernelContext_5)->entryPointParams_0->winEnd_0, (&kernelContext_5)->entryPointParams_0->binsize_0, (&kernelContext_5)->entryPointParams_0->binShift_0, (&kernelContext_5)->entryPointParams_0->nbins_0, (&kernelContext_5)->entryPointParams_0->thrBits_0, &kernelContext_5);



    return;
}

