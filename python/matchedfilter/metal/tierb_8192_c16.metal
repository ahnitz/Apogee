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


#line 142 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_8192_fusedTierB_c16.slang"
half2 cload_0(uint device* b_0, uint i_0)
{

#line 143
    uint p_0 = b_0[i_0];

#line 143
    return half2(half((as_type<half>((ushort)((p_0 & 65535U))))), half((as_type<half>((ushort)((p_0 >> 16U))))));
}


#line 186
half2 cmulConj_0(half2 a_0, half2 b_1)
{

#line 186
    half _S2 = a_0.x;

#line 186
    half _S3 = b_1.x;

#line 186
    half _S4 = a_0.y;

#line 186
    half _S5 = b_1.y;

#line 186
    return half2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 335
void r4_0(half2 thread* a_1, half2 thread* b_2, half2 thread* c_0, half2 thread* d_0)
{
    half2 t0_0 = *a_1 + *c_0;

#line 337
    half2 t1_0 = *a_1 - *c_0;

#line 337
    half2 t2_0 = *b_2 + *d_0;

#line 337
    half2 t3_0 = *b_2 - *d_0;
    half2 j3_0 = half2(- t3_0.y, t3_0.x);
    *a_1 = t0_0 + t2_0;

#line 339
    *b_2 = t1_0 + j3_0;

#line 339
    *c_0 = t0_0 - t2_0;

#line 339
    *d_0 = t1_0 - j3_0;
    return;
}


#line 185
half2 cmul_0(half2 a_2, half2 b_3)
{

#line 185
    half _S6 = a_2.x;

#line 185
    half _S7 = b_3.x;

#line 185
    half _S8 = a_2.y;

#line 185
    half _S9 = b_3.y;

#line 185
    return half2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 371
void dft16_0(array<half2, int(16)> thread* r_0)
{
    half2 W1_0 = half2(0.923828125h, 0.382568359375h);
    half2 W2_0 = half2(0.70703125h, 0.70703125h);
    half2 W3_0 = half2(0.382568359375h, 0.923828125h);
    half2 W4_0 = half2(0.0h, 1.0h);
    half2 W6_0 = half2(-0.70703125h, 0.70703125h);
    half2 W9_0 = half2(-0.923828125h, -0.382568359375h);

#line 378
    uint n1_0 = 0U;
    for(;;)
    {

#line 379
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 379
            break;
        }

#line 379
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 379
        n1_0 = n1_0 + 1U;

#line 379
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 380
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 380
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 381
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 381
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 382
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 382
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 382
    uint k2_0 = 0U;
    for(;;)
    {

#line 383
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 383
            break;
        }

#line 383
        uint _S10 = 4U * k2_0;

#line 383
        r4_0(&(*r_0)[_S10], &(*r_0)[_S10 + 1U], &(*r_0)[_S10 + 2U], &(*r_0)[_S10 + 3U]);

#line 383
        k2_0 = k2_0 + 1U;

#line 383
    }

    half2 t_0 = (*r_0)[int(1)];

#line 385
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 385
    (*r_0)[int(4)] = t_0;
    half2 t_1 = (*r_0)[int(2)];

#line 386
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 386
    (*r_0)[int(8)] = t_1;
    half2 t_2 = (*r_0)[int(3)];

#line 387
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 387
    (*r_0)[int(12)] = t_2;
    half2 t_3 = (*r_0)[int(6)];

#line 388
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 388
    (*r_0)[int(9)] = t_3;
    half2 t_4 = (*r_0)[int(7)];

#line 389
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 389
    (*r_0)[int(13)] = t_4;
    half2 t_5 = (*r_0)[int(11)];

#line 390
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 390
    (*r_0)[int(14)] = t_5;
    return;
}


#line 456
void dftR_0(array<half2, int(16)> thread* r_1)
{

    dft16_0(r_1);

#line 465
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


#line 168 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_8192_fusedTierB_c16.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    uint device* entryPointParams_data_0;
    uint device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    uint _stgBase_0;
    uint _tid_0;
    array<uint, int(8192)> threadgroup* stg_0;
};


#line 168
void stgPut_0(uint i_1, half2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 168
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + i_1] = (uint(as_type<ushort>(v_0[0U])) & 65535U) | (uint(as_type<ushort>(v_0[1U])) << 16U);

#line 168
    return;
}


#line 169
half2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 169
    return half2(as_type<half>(ushort(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + i_2]) & 65535U)), as_type<half>(ushort((((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + i_2]) >> 16U) & 65535U)));
}


#line 496
void exchange_0(array<half2, int(16)> thread* r_2, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 496
    uint j_0;

#line 507
    thread array<half2, int(16)> out_0;

#line 507
    uint z_0 = 0U;
    for(;;)
    {

#line 508
        if(z_0 < 16U)
        {
        }
        else
        {

#line 508
            break;
        }

#line 508
        out_0[z_0] = half2(0.0h, 0.0h);

#line 508
        z_0 = z_0 + 1U;

#line 508
    }
    uint _S11 = (1U << lgSpan_0) - 1U;
    uint _S12 = (1U << lgLen_0) - 1U;

#line 510
    uint c_1 = 0U;
    for(;;)
    {

#line 511
        if(c_1 < 1U)
        {
        }
        else
        {

#line 511
            break;
        }

#line 512
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 512
        j_0 = 0U;
        for(;;)
        {

#line 513
            if(j_0 < 16U)
            {
            }
            else
            {

#line 513
                break;
            }

#line 513
            stgPut_0(j_0 * 512U + kernelContext_2->_tid_0, (*r_2)[c_1 * 16U + j_0], kernelContext_2);

#line 513
            j_0 = j_0 + 1U;

#line 513
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 514
        uint d_1 = 0U;
        for(;;)
        {

#line 515
            if(d_1 < 16U)
            {
            }
            else
            {

#line 515
                break;
            }
            uint b_4 = ((*want_0)[d_1]) >> lgLen_0;

#line 517
            uint rem_0 = ((*want_0)[d_1]) & _S12;
            uint i_3 = rem_0 >> lgSpan_0;

#line 518
            uint ln_0 = rem_0 & _S11;
            uint _S13 = c_1 * 16U;

#line 519
            bool _S14;

#line 519
            if(i_3 >= _S13)
            {

#line 519
                _S14 = i_3 < ((c_1 + 1U) * 16U);

#line 519
            }
            else
            {

#line 519
                _S14 = false;

#line 519
            }

#line 519
            if(_S14)
            {

#line 519
                half2 _S15 = stgGet_0((i_3 - _S13) * 512U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S15;

#line 519
            }

#line 515
            d_1 = d_1 + 1U;

#line 515
        }

#line 511
        c_1 = c_1 + 1U;

#line 511
    }

#line 511
    j_0 = 0U;

#line 523
    for(;;)
    {

#line 523
        if(j_0 < 16U)
        {
        }
        else
        {

#line 523
            break;
        }

#line 523
        (*r_2)[j_0] = out_0[j_0];

#line 523
        j_0 = j_0 + 1U;

#line 523
    }
    return;
}


#line 346
void dft2_0(array<half2, int(16)> thread* r_3, uint o_0)
{
    half2 a_3 = (*r_3)[o_0];

#line 348
    half2 b_5 = (*r_3)[o_0 + 1U];

#line 348
    (*r_3)[o_0] = (*r_3)[o_0] + (*r_3)[o_0 + 1U];

#line 348
    (*r_3)[o_0 + 1U] = a_3 - b_5;
    return;
}


#line 474
void innermost_0(array<half2, int(16)> thread* r_4)
{

#line 474
    uint b_6 = 0U;

#line 484
    for(;;)
    {

#line 484
        if(b_6 < 8U)
        {
        }
        else
        {

#line 484
            break;
        }

#line 484
        dft2_0(r_4, b_6 * 2U);

#line 484
        b_6 = b_6 + 1U;

#line 484
    }

    return;
}


#line 578
void transform_0(array<half2, int(16)> thread* r_5, uint tid_0, KernelContext_0 thread* kernelContext_3)
{

#line 578
    uint z_1;

#line 578
    uint _S16;

#line 578
    uint k2_1;

#line 578
    float cr_0;

#line 578
    float ci_0;

#line 578
    uint _S17;

#line 578
    uint d_2;

#line 578
    uint _S18;

#line 578
    uint _S19;

#line 578
    for(;;)
    {

#line 578
        for(;;)
        {
            for(;;)
            {

#line 581
                thread array<uint, int(16)> want_1;

#line 581
                z_1 = 0U;
                for(;;)
                {

#line 582
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 582
                        break;
                    }

#line 582
                    want_1[z_1] = 0U;

#line 582
                    z_1 = z_1 + 1U;

#line 582
                }



                uint lgTB_0 = firstbithigh_0(512U);

#line 586
                _S16 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(8192U);

                uint lane_0 = tid_0 & 511U;

                dftR_0(r_5);

#line 596
                float a1_0 = 6.28318548202514648f * float(lane_0) / 8192.0f;
                float _S20 = cos(a1_0);

#line 597
                float _S21 = sin(a1_0);

#line 597
                k2_1 = 0U;

#line 597
                cr_0 = 1.0f;

#line 597
                ci_0 = 0.0f;

                for(;;)
                {

#line 599
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 599
                        break;
                    }

#line 600
                    (*r_5)[k2_1] = cmul_0((*r_5)[k2_1], half2(half(cr_0), half(ci_0)));
                    float nr_0 = cr_0 * _S20 - ci_0 * _S21;
                    float _S22 = cr_0 * _S21 + ci_0 * _S20;

#line 599
                    k2_1 = k2_1 + 1U;

#line 599
                    cr_0 = nr_0;

#line 599
                    ci_0 = _S22;

#line 599
                }

#line 609
                uint _S23 = max(512U, 1U);

#line 609
                uint _S24 = 16U / _S23;
                uint _S25 = max(32U, 1U);

#line 610
                _S17 = _S25;
                uint _S26 = tid_0 / _S25;

#line 611
                uint _S27 = tid_0 % _S25;

#line 611
                d_2 = 0U;
                for(;;)
                {

#line 612
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 612
                        break;
                    }

#line 613
                    uint j_1 = d_2 / _S23;

#line 613
                    uint m_0 = d_2 % _S23;
                    want_1[d_2] = _S26 * 512U + _S27 + _S25 * d_2;

#line 612
                    d_2 = d_2 + 1U;

#line 612
                }

#line 612
                thread array<uint, int(16)> _S28 = want_1;

#line 612
                exchange_0(r_5, &_S28, lgLn_0, lgTB_0, kernelContext_3);

#line 580
                break;
            }

#line 580
            break;
        }

#line 580
        for(;;)
        {

#line 580
            for(;;)
            {

#line 581
                thread array<uint, int(16)> want_2;

#line 581
                z_1 = 0U;
                for(;;)
                {

#line 582
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 582
                        break;
                    }

#line 582
                    want_2[z_1] = 0U;

#line 582
                    z_1 = z_1 + 1U;

#line 582
                }



                uint lgTB_1 = firstbithigh_0(32U);

#line 586
                _S18 = lgTB_1;


                uint lane_1 = tid_0 & 31U;

                dftR_0(r_5);

#line 596
                float a1_1 = 6.28318548202514648f * float(lane_1) / 512.0f;
                float _S29 = cos(a1_1);

#line 597
                float _S30 = sin(a1_1);

#line 597
                k2_1 = 0U;

#line 597
                cr_0 = 1.0f;

#line 597
                ci_0 = 0.0f;

                for(;;)
                {

#line 599
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 599
                        break;
                    }

#line 600
                    (*r_5)[k2_1] = cmul_0((*r_5)[k2_1], half2(half(cr_0), half(ci_0)));
                    float nr_1 = cr_0 * _S29 - ci_0 * _S30;
                    float _S31 = cr_0 * _S30 + ci_0 * _S29;

#line 599
                    k2_1 = k2_1 + 1U;

#line 599
                    cr_0 = nr_1;

#line 599
                    ci_0 = _S31;

#line 599
                }

#line 609
                uint _S32 = 16U / _S17;
                uint _S33 = max(2U, 1U);

#line 610
                _S19 = _S33;
                uint _S34 = tid_0 / _S33;

#line 611
                uint _S35 = tid_0 % _S33;

#line 611
                d_2 = 0U;
                for(;;)
                {

#line 612
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 612
                        break;
                    }

#line 613
                    uint j_2 = d_2 / _S17;

#line 613
                    uint m_1 = d_2 % _S17;
                    want_2[d_2] = _S34 * 32U + _S35 + _S33 * d_2;

#line 612
                    d_2 = d_2 + 1U;

#line 612
                }

#line 612
                thread array<uint, int(16)> _S36 = want_2;

#line 612
                exchange_0(r_5, &_S36, _S16, lgTB_1, kernelContext_3);

#line 580
                break;
            }

#line 580
            break;
        }

#line 580
        for(;;)
        {

#line 580
            for(;;)
            {

#line 581
                thread array<uint, int(16)> want_3;

#line 581
                z_1 = 0U;
                for(;;)
                {

#line 582
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 582
                        break;
                    }

#line 582
                    want_3[z_1] = 0U;

#line 582
                    z_1 = z_1 + 1U;

#line 582
                }



                uint lgTB_2 = firstbithigh_0(2U);

                uint _S37 = tid_0 >> lgTB_2;
                uint lane_2 = tid_0 & 1U;

                dftR_0(r_5);

#line 596
                float a1_2 = 6.28318548202514648f * float(lane_2) / 32.0f;
                float _S38 = cos(a1_2);

#line 597
                float _S39 = sin(a1_2);

#line 597
                k2_1 = 0U;

#line 597
                cr_0 = 1.0f;

#line 597
                ci_0 = 0.0f;

                for(;;)
                {

#line 599
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 599
                        break;
                    }

#line 600
                    (*r_5)[k2_1] = cmul_0((*r_5)[k2_1], half2(half(cr_0), half(ci_0)));
                    float nr_2 = cr_0 * _S38 - ci_0 * _S39;
                    float _S40 = cr_0 * _S39 + ci_0 * _S38;

#line 599
                    k2_1 = k2_1 + 1U;

#line 599
                    cr_0 = nr_2;

#line 599
                    ci_0 = _S40;

#line 599
                }

#line 609
                uint _S41 = 16U / _S19;
                uint _S42 = max(0U, 1U);
                uint _S43 = tid_0 / _S42;

#line 611
                uint _S44 = tid_0 % _S42;

#line 611
                d_2 = 0U;
                for(;;)
                {

#line 612
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 612
                        break;
                    }

#line 613
                    uint j_3 = d_2 / _S19;

#line 613
                    uint m_2 = d_2 % _S19;
                    want_3[d_2] = _S37 * 32U + (lane_2 * _S41 + j_3) * 2U + m_2;

#line 612
                    d_2 = d_2 + 1U;

#line 612
                }

#line 612
                thread array<uint, int(16)> _S45 = want_3;

#line 612
                exchange_0(r_5, &_S45, _S18, lgTB_2, kernelContext_3);

#line 580
                break;
            }

#line 580
            break;
        }

#line 580
        break;
    }

#line 620
    innermost_0(r_5);
    return;
}


#line 547
uint lgOf_0(uint i_4)
{

#line 547
    uint _S46;

#line 547
    if(i_4 < 3U)
    {

#line 547
        _S46 = 4U;

#line 547
    }
    else
    {

#line 547
        _S46 = 1U;

#line 547
    }

#line 547
    return _S46;
}


#line 549
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(3U);

    uint x_0 = slot_0 >> lg_0;

#line 553
    uint lg_1 = lgOf_0(2U);

    uint x_1 = x_0 >> lg_1;

#line 553
    uint lg_2 = lgOf_0(1U);

#line 553
    uint lg_3 = lgOf_0(0U);

#line 558
    return (((((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | (x_1 & ((1U << lg_2) - 1U))) << lg_3) | ((x_1 >> lg_2) & ((1U << lg_3) - 1U));
}


#line 627
void filterOne_0(uint pair_0, uint d_3, uint t_6, uint tid_1, const array<half2, int(16)> thread* dreg_0, uint device* data_0, uint device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_4)
{


    bool live_0;

#line 644
    thread array<half2, int(16)> r_6;

#line 644
    uint n2_0 = 0U;



    for(;;)
    {

#line 648
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 648
            break;
        }

#line 649
        r_6[n2_0] = cmulConj_0((*dreg_0)[n2_0], cload_0(tmpl_0, t_6 * 8192U + tid_1 + 512U * n2_0));

#line 648
        n2_0 = n2_0 + 1U;

#line 648
    }

#line 648
    transform_0(&r_6, tid_1, kernelContext_4);

#line 674
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 680
    bool _S47 = tid_1 == 0U;

#line 680
    if(_S47)
    {

#line 680
        (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0] = thrBits_1;

#line 680
    }



    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;

#line 686
    uint i_5 = 0U;

    for(;;)
    {

#line 688
        if(i_5 < 16U)
        {
        }
        else
        {

#line 688
            break;
        }

#line 689
        uint idx_0 = slotToIndex_0(tid_1 * 16U + i_5);
        if(idx_0 >= winStart_1)
        {

#line 690
            live_0 = idx_0 < winEnd_1;

#line 690
        }
        else
        {

#line 690
            live_0 = false;

#line 690
        }



        float _rx_0 = float(r_6[i_5].x);

#line 694
        float _ry_0 = float(r_6[i_5].y);
        if(live_0)
        {

#line 695
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 695
        }
        else
        {

#line 695
            n2_0 = 0U;

#line 695
        }

#line 695
        myMag_0[i_5] = n2_0;

#line 688
        i_5 = i_5 + 1U;

#line 688
    }

#line 688
    uint bestBits_0 = thrBits_1;

#line 688
    i_5 = 0U;

#line 723
    for(;;)
    {

#line 723
        if(i_5 < 16U)
        {
        }
        else
        {

#line 723
            break;
        }

#line 723
        uint _S48 = max(bestBits_0, myMag_0[i_5]);

#line 723
        uint i_6 = i_5 + 1U;

#line 723
        bestBits_0 = _S48;

#line 723
        i_5 = i_6;

#line 723
    }

    uint wm_0 = simd_max(bestBits_0);
    bool _S49 = simd_is_first();

#line 726
    if(_S49)
    {

#line 726
        live_0 = wm_0 > thrBits_1;

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

#line 726
        uint _S50 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0])), wm_0, memory_order_relaxed);

#line 726
    }

#line 741
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 741
    i_5 = 0U;

#line 746
    for(;;)
    {

#line 746
        if(i_5 < 16U)
        {
        }
        else
        {

#line 746
            break;
        }
        if((myMag_0[i_5]) > thrBits_1)
        {

#line 748
            live_0 = ((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0]) == myMag_0[i_5];

#line 748
        }
        else
        {

#line 748
            live_0 = false;

#line 748
        }

#line 748
        if(live_0)
        {

#line 754
            *(peakIdx_0+pair_0) = int(slotToIndex_0(tid_1 * 16U + i_5));

#line 754
            *(peakVal_0+pair_0) = packed_float2(float2(float(r_6[i_5].x), float(r_6[i_5].y))) ;

#line 748
        }

#line 746
        i_5 = i_5 + 1U;

#line 746
    }

#line 761
    if(_S47)
    {

#line 761
        live_0 = ((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0]) == thrBits_1;

#line 761
    }
    else
    {

#line 761
        live_0 = false;

#line 761
    }

#line 761
    if(live_0)
    {

#line 769
        *(peakIdx_0+pair_0) = int(-1);

#line 769
        *(peakVal_0+pair_0) = packed_float2(float2(0.0f, 0.0f)) ;

#line 761
    }

#line 773
    return;
}


#line 899
void filterPair_0(uint pair_1, uint tid_2, uint device* data_1, uint device* tmpl_1, int device* peakIdx_1, packed_float2 device* peakVal_1, uint ntmpl_1, uint winStart_2, uint winEnd_2, uint binsize_2, int binShift_2, uint nbins_2, uint thrBits_2, KernelContext_0 thread* kernelContext_5)
{

#line 905
    kernelContext_5->_tid_0 = tid_2;

#line 915
    uint _S51 = pair_1 / ntmpl_1;

#line 915
    uint _S52 = pair_1 % ntmpl_1;
    thread array<half2, int(16)> dreg_1;

#line 916
    uint n2_1 = 0U;

    for(;;)
    {

#line 918
        if(n2_1 < 16U)
        {
        }
        else
        {

#line 918
            break;
        }

#line 919
        dreg_1[n2_1] = cload_0(data_1, _S51 * 8192U + tid_2 + 512U * n2_1);

#line 918
        n2_1 = n2_1 + 1U;

#line 918
    }

#line 918
    uint k_0 = 0U;

#line 929
    for(;;)
    {

#line 929
        if(k_0 < 1U)
        {
        }
        else
        {

#line 929
            break;
        }

#line 930
        uint _S53 = pair_1 + k_0;

#line 930
        uint _S54 = _S52 + k_0;

#line 930
        thread array<half2, int(16)> _S55 = dreg_1;

#line 930
        filterOne_0(_S53, _S51, _S54, tid_2, &_S55, data_1, tmpl_1, peakIdx_1, peakVal_1, winStart_2, winEnd_2, binsize_2, binShift_2, nbins_2, thrBits_2, kernelContext_5);

#line 929
        k_0 = k_0 + 1U;

#line 929
    }



    return;
}


[[kernel]] void fusedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], uint device* entryPointParams_data_1 [[buffer(1)]], uint device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]])
{

#line 937
    thread KernelContext_0 kernelContext_6;

#line 937
    (&kernelContext_6)->entryPointParams_0 = entryPointParams_1;

#line 937
    (&kernelContext_6)->entryPointParams_data_0 = entryPointParams_data_1;

#line 937
    (&kernelContext_6)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 937
    (&kernelContext_6)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 937
    (&kernelContext_6)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 937
    threadgroup array<uint, int(8192)> stg_1;

#line 937
    (&kernelContext_6)->stg_0 = &stg_1;

#line 954
    uint _pr_0 = gid_0.x;

#line 954
    uint _t_0 = lid_0.x;
    (&kernelContext_6)->_stgBase_0 = 0U;

#line 955
    filterPair_0(_pr_0, _t_0, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_6);

#line 963
    return;
}

