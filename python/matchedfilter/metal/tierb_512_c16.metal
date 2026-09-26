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


#line 145 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_512_fusedTierB_c16.slang"
half2 cload_0(uint device* b_0, uint i_0)
{

#line 146
    uint p_0 = b_0[i_0];

#line 146
    return half2(half((as_type<half>((ushort)((p_0 & 65535U))))), half((as_type<half>((ushort)((p_0 >> 16U))))));
}


#line 189
half2 cmulConj_0(half2 a_0, half2 b_1)
{

#line 189
    half _S2 = a_0.x;

#line 189
    half _S3 = b_1.x;

#line 189
    half _S4 = a_0.y;

#line 189
    half _S5 = b_1.y;

#line 189
    return half2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 338
void r4_0(half2 thread* a_1, half2 thread* b_2, half2 thread* c_0, half2 thread* d_0)
{
    half2 t0_0 = *a_1 + *c_0;

#line 340
    half2 t1_0 = *a_1 - *c_0;

#line 340
    half2 t2_0 = *b_2 + *d_0;

#line 340
    half2 t3_0 = *b_2 - *d_0;
    half2 j3_0 = half2(- t3_0.y, t3_0.x);
    *a_1 = t0_0 + t2_0;

#line 342
    *b_2 = t1_0 + j3_0;

#line 342
    *c_0 = t0_0 - t2_0;

#line 342
    *d_0 = t1_0 - j3_0;
    return;
}


#line 188
half2 cmul_0(half2 a_2, half2 b_3)
{

#line 188
    half _S6 = a_2.x;

#line 188
    half _S7 = b_3.x;

#line 188
    half _S8 = a_2.y;

#line 188
    half _S9 = b_3.y;

#line 188
    return half2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 374
void dft16_0(array<half2, int(16)> thread* r_0)
{
    half2 W1_0 = half2(0.923828125h, 0.382568359375h);
    half2 W2_0 = half2(0.70703125h, 0.70703125h);
    half2 W3_0 = half2(0.382568359375h, 0.923828125h);
    half2 W4_0 = half2(0.0h, 1.0h);
    half2 W6_0 = half2(-0.70703125h, 0.70703125h);
    half2 W9_0 = half2(-0.923828125h, -0.382568359375h);

#line 381
    uint n1_0 = 0U;
    for(;;)
    {

#line 382
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 382
            break;
        }

#line 382
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 382
        n1_0 = n1_0 + 1U;

#line 382
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 383
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 383
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 384
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 384
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 385
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 385
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 385
    uint k2_0 = 0U;
    for(;;)
    {

#line 386
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 386
            break;
        }

#line 386
        uint _S10 = 4U * k2_0;

#line 386
        r4_0(&(*r_0)[_S10], &(*r_0)[_S10 + 1U], &(*r_0)[_S10 + 2U], &(*r_0)[_S10 + 3U]);

#line 386
        k2_0 = k2_0 + 1U;

#line 386
    }

    half2 t_0 = (*r_0)[int(1)];

#line 388
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 388
    (*r_0)[int(4)] = t_0;
    half2 t_1 = (*r_0)[int(2)];

#line 389
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 389
    (*r_0)[int(8)] = t_1;
    half2 t_2 = (*r_0)[int(3)];

#line 390
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 390
    (*r_0)[int(12)] = t_2;
    half2 t_3 = (*r_0)[int(6)];

#line 391
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 391
    (*r_0)[int(9)] = t_3;
    half2 t_4 = (*r_0)[int(7)];

#line 392
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 392
    (*r_0)[int(13)] = t_4;
    half2 t_5 = (*r_0)[int(11)];

#line 393
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 393
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


#line 171 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_512_fusedTierB_c16.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    uint device* entryPointParams_data_0;
    uint device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    uint _stgBase_0;
    uint _tid_0;
    array<uint, int(512)> threadgroup* stg_0;
};


#line 171
void stgPut_0(uint i_1, half2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 171
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + i_1] = (uint(as_type<ushort>(v_0[0U])) & 65535U) | (uint(as_type<ushort>(v_0[1U])) << 16U);

#line 171
    return;
}


#line 172
half2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 172
    return half2(as_type<half>(ushort(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + i_2]) & 65535U)), as_type<half>(ushort((((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + i_2]) >> 16U) & 65535U)));
}


#line 499
void exchange_0(array<half2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 499
    uint j_0;

#line 510
    thread array<half2, int(16)> out_0;

#line 510
    uint z_0 = 0U;
    for(;;)
    {

#line 511
        if(z_0 < 16U)
        {
        }
        else
        {

#line 511
            break;
        }

#line 511
        out_0[z_0] = half2(0.0h, 0.0h);

#line 511
        z_0 = z_0 + 1U;

#line 511
    }
    uint _S11 = (1U << lgSpan_0) - 1U;
    uint _S12 = (1U << lgLen_0) - 1U;

#line 513
    uint c_1 = 0U;
    for(;;)
    {

#line 514
        if(c_1 < 1U)
        {
        }
        else
        {

#line 514
            break;
        }

#line 515
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 515
        j_0 = 0U;
        for(;;)
        {

#line 516
            if(j_0 < 16U)
            {
            }
            else
            {

#line 516
                break;
            }

#line 516
            stgPut_0(j_0 * 32U + kernelContext_2->_tid_0, (*r_1)[c_1 * 16U + j_0], kernelContext_2);

#line 516
            j_0 = j_0 + 1U;

#line 516
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 517
        uint d_1 = 0U;
        for(;;)
        {

#line 518
            if(d_1 < 16U)
            {
            }
            else
            {

#line 518
                break;
            }
            uint b_4 = ((*want_0)[d_1]) >> lgLen_0;

#line 520
            uint rem_0 = ((*want_0)[d_1]) & _S12;
            uint i_3 = rem_0 >> lgSpan_0;

#line 521
            uint ln_0 = rem_0 & _S11;
            uint _S13 = c_1 * 16U;

#line 522
            bool _S14;

#line 522
            if(i_3 >= _S13)
            {

#line 522
                _S14 = i_3 < ((c_1 + 1U) * 16U);

#line 522
            }
            else
            {

#line 522
                _S14 = false;

#line 522
            }

#line 522
            if(_S14)
            {

#line 522
                half2 _S15 = stgGet_0((i_3 - _S13) * 32U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S15;

#line 522
            }

#line 518
            d_1 = d_1 + 1U;

#line 518
        }

#line 514
        c_1 = c_1 + 1U;

#line 514
    }

#line 514
    j_0 = 0U;

#line 526
    for(;;)
    {

#line 526
        if(j_0 < 16U)
        {
        }
        else
        {

#line 526
            break;
        }

#line 526
        (*r_1)[j_0] = out_0[j_0];

#line 526
        j_0 = j_0 + 1U;

#line 526
    }
    return;
}


#line 349
void dft2_0(array<half2, int(16)> thread* r_2, uint o_0)
{
    half2 a_3 = (*r_2)[o_0];

#line 351
    half2 b_5 = (*r_2)[o_0 + 1U];

#line 351
    (*r_2)[o_0] = (*r_2)[o_0] + (*r_2)[o_0 + 1U];

#line 351
    (*r_2)[o_0 + 1U] = a_3 - b_5;
    return;
}


#line 477
void innermost_0(array<half2, int(16)> thread* r_3)
{

#line 477
    uint b_6 = 0U;

#line 487
    for(;;)
    {

#line 487
        if(b_6 < 8U)
        {
        }
        else
        {

#line 487
            break;
        }

#line 487
        dft2_0(r_3, b_6 * 2U);

#line 487
        b_6 = b_6 + 1U;

#line 487
    }

    return;
}


#line 581
void transform_0(array<half2, int(16)> thread* r_4, uint tid_0, KernelContext_0 thread* kernelContext_3)
{

#line 581
    uint z_1;

#line 581
    uint _S16;

#line 581
    uint k2_1;

#line 581
    float cr_0;

#line 581
    float ci_0;

#line 581
    uint _S17;

#line 581
    uint d_2;

#line 581
    for(;;)
    {

#line 581
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



                uint lgTB_0 = firstbithigh_0(32U);

#line 13
                _S16 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(512U);

                uint lane_0 = tid_0 & 31U;


                dft16_0(r_4);

#line 27
                float a1_0 = 6.28318548202514648f * float(lane_0) / 512.0f;
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
                    (*r_4)[k2_1] = cmul_0((*r_4)[k2_1], half2(half(cr_0), half(ci_0)));
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
                uint _S21 = max(32U, 1U);

#line 40
                uint _S22 = 16U / _S21;
                uint _S23 = max(2U, 1U);

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
                    uint j_1 = d_2 / _S21;

#line 44
                    uint m_0 = d_2 % _S21;
                    want_1[d_2] = _S24 * 32U + _S25 + _S23 * d_2;

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



                uint lgTB_1 = firstbithigh_0(2U);

                uint _S27 = tid_0 >> lgTB_1;
                uint lane_1 = tid_0 & 1U;


                dft16_0(r_4);

#line 27
                float a1_1 = 6.28318548202514648f * float(lane_1) / 32.0f;
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
                    (*r_4)[k2_1] = cmul_0((*r_4)[k2_1], half2(half(cr_0), half(ci_0)));
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
                    uint j_2 = d_2 / _S17;

#line 44
                    uint m_1 = d_2 % _S17;
                    want_2[d_2] = _S27 * 32U + (lane_1 * _S31 + j_2) * 2U + m_1;

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

#line 584 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_512_fusedTierB_c16.slang"
    return;
}


#line 550
uint lgOf_0(uint i_4)
{

#line 550
    uint _S36;

#line 550
    if(i_4 < 2U)
    {

#line 550
        _S36 = 4U;

#line 550
    }
    else
    {

#line 550
        _S36 = 1U;

#line 550
    }

#line 550
    return _S36;
}


#line 552
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(2U);

    uint x_0 = slot_0 >> lg_0;

#line 556
    uint lg_1 = lgOf_0(1U);

#line 556
    uint lg_2 = lgOf_0(0U);

#line 561
    return (((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | ((x_0 >> lg_1) & ((1U << lg_2) - 1U));
}


#line 590
void filterOne_0(uint pair_0, uint d_3, uint t_6, uint tid_1, const array<half2, int(16)> thread* dreg_0, uint device* data_0, uint device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_4)
{


    bool live_0;

#line 613
    thread array<half2, int(16)> r_5;

#line 613
    uint n2_0 = 0U;



    for(;;)
    {

#line 617
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 617
            break;
        }

#line 618
        r_5[n2_0] = cmulConj_0((*dreg_0)[n2_0], cload_0(tmpl_0, t_6 * 512U + tid_1 + 32U * n2_0));

#line 617
        n2_0 = n2_0 + 1U;

#line 617
    }

#line 617
    transform_0(&r_5, tid_1, kernelContext_4);

#line 643
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 649
    bool _S37 = tid_1 == 0U;

#line 649
    if(_S37)
    {

#line 649
        (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0] = thrBits_1;

#line 649
        (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U] = 4294967295U;

#line 649
    }

#line 654
    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;

#line 656
    uint i_5 = 0U;

    for(;;)
    {

#line 658
        if(i_5 < 16U)
        {
        }
        else
        {

#line 658
            break;
        }

#line 659
        uint idx_0 = slotToIndex_0(tid_1 * 16U + i_5);
        if(idx_0 >= winStart_1)
        {

#line 660
            live_0 = idx_0 < winEnd_1;

#line 660
        }
        else
        {

#line 660
            live_0 = false;

#line 660
        }



        float _rx_0 = float(r_5[i_5].x);

#line 664
        float _ry_0 = float(r_5[i_5].y);
        if(live_0)
        {

#line 665
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 665
        }
        else
        {

#line 665
            n2_0 = 0U;

#line 665
        }

#line 665
        myMag_0[i_5] = n2_0;

#line 658
        i_5 = i_5 + 1U;

#line 658
    }

#line 658
    uint bestBits_0 = thrBits_1;

#line 658
    i_5 = 0U;

#line 693
    for(;;)
    {

#line 693
        if(i_5 < 16U)
        {
        }
        else
        {

#line 693
            break;
        }

#line 693
        uint _S38 = max(bestBits_0, myMag_0[i_5]);

#line 693
        uint i_6 = i_5 + 1U;

#line 693
        bestBits_0 = _S38;

#line 693
        i_5 = i_6;

#line 693
    }

    uint wm_0 = simd_max(bestBits_0);
    bool _S39 = simd_is_first();

#line 696
    if(_S39)
    {

#line 696
        live_0 = wm_0 > thrBits_1;

#line 696
    }
    else
    {

#line 696
        live_0 = false;

#line 696
    }

#line 696
    if(live_0)
    {

#line 696
        uint _S40 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0])), wm_0, memory_order_relaxed);

#line 696
    }

#line 711
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 711
    uint winner_0 = 4294967295U;

#line 711
    i_5 = 0U;

#line 721
    for(;;)
    {

#line 721
        if(i_5 < 16U)
        {
        }
        else
        {

#line 721
            break;
        }

#line 722
        if((myMag_0[i_5]) > thrBits_1)
        {

#line 722
            live_0 = (myMag_0[i_5]) == (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0];

#line 722
        }
        else
        {

#line 722
            live_0 = false;

#line 722
        }

#line 722
        if(live_0)
        {

#line 722
            winner_0 = min(winner_0, tid_1 * 16U + i_5);

#line 722
        }

#line 721
        i_5 = i_5 + 1U;

#line 721
    }



    uint waveWinner_0 = simd_min(winner_0);
    bool _S41 = simd_is_first();

#line 726
    if(_S41)
    {

#line 726
        live_0 = waveWinner_0 != 4294967295U;

#line 726
    }
    else
    {

#line 726
        live_0 = false;

#line 726
    }

#line 726
    if(live_0)
    {

#line 727
        uint _S42 = atomic_fetch_min_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U])), waveWinner_0, memory_order_relaxed);

#line 726
    }

#line 731
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 731
    i_5 = 0U;
    for(;;)
    {

#line 732
        if(i_5 < 16U)
        {
        }
        else
        {

#line 732
            break;
        }

#line 733
        uint _S43 = tid_1 * 16U + i_5;

#line 733
        if(_S43 == (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U])
        {

#line 734
            *(peakIdx_0+pair_0) = int(slotToIndex_0(_S43));

#line 734
            *(peakVal_0+pair_0) = packed_float2(float2(float(r_5[i_5].x), float(r_5[i_5].y))) ;

#line 733
        }

#line 732
        i_5 = i_5 + 1U;

#line 732
    }

#line 738
    if(_S37)
    {

#line 738
        live_0 = ((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U]) == 4294967295U;

#line 738
    }
    else
    {

#line 738
        live_0 = false;

#line 738
    }

#line 738
    if(live_0)
    {

#line 739
        *(peakIdx_0+pair_0) = int(-1);

#line 739
        *(peakVal_0+pair_0) = packed_float2(float2(0.0f, 0.0f)) ;

#line 738
    }

#line 771
    return;
}


#line 910
void filterPair_0(uint pair_1, uint tid_2, uint device* data_1, uint device* tmpl_1, int device* peakIdx_1, packed_float2 device* peakVal_1, uint ntmpl_1, uint winStart_2, uint winEnd_2, uint binsize_2, int binShift_2, uint nbins_2, uint thrBits_2, KernelContext_0 thread* kernelContext_5)
{

#line 916
    kernelContext_5->_tid_0 = tid_2;

#line 926
    uint _S44 = pair_1 / ntmpl_1;

#line 926
    uint _S45 = pair_1 % ntmpl_1;
    thread array<half2, int(16)> dreg_1;

#line 927
    uint n2_1 = 0U;

    for(;;)
    {

#line 929
        if(n2_1 < 16U)
        {
        }
        else
        {

#line 929
            break;
        }

#line 930
        dreg_1[n2_1] = cload_0(data_1, _S44 * 512U + tid_2 + 32U * n2_1);

#line 929
        n2_1 = n2_1 + 1U;

#line 929
    }

#line 929
    uint k_0 = 0U;

#line 940
    for(;;)
    {

#line 940
        if(k_0 < 1U)
        {
        }
        else
        {

#line 940
            break;
        }

#line 941
        uint _S46 = pair_1 + k_0;

#line 941
        uint _S47 = _S45 + k_0;

#line 941
        thread array<half2, int(16)> _S48 = dreg_1;

#line 941
        filterOne_0(_S46, _S44, _S47, tid_2, &_S48, data_1, tmpl_1, peakIdx_1, peakVal_1, winStart_2, winEnd_2, binsize_2, binShift_2, nbins_2, thrBits_2, kernelContext_5);

#line 940
        k_0 = k_0 + 1U;

#line 940
    }



    return;
}


[[kernel]] void fusedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], uint device* entryPointParams_data_1 [[buffer(1)]], uint device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]])
{

#line 948
    thread KernelContext_0 kernelContext_6;

#line 948
    (&kernelContext_6)->entryPointParams_0 = entryPointParams_1;

#line 948
    (&kernelContext_6)->entryPointParams_data_0 = entryPointParams_data_1;

#line 948
    (&kernelContext_6)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 948
    (&kernelContext_6)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 948
    (&kernelContext_6)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 948
    threadgroup array<uint, int(512)> stg_1;

#line 948
    (&kernelContext_6)->stg_0 = &stg_1;

#line 965
    uint _pr_0 = gid_0.x;

#line 965
    uint _t_0 = lid_0.x;
    (&kernelContext_6)->_stgBase_0 = 0U;

#line 966
    filterPair_0(_pr_0, _t_0, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_6);

#line 974
    return;
}

