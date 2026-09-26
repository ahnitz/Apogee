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


#line 146 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_32768_refineListed.slang"
float2 cload_0(packed_float2 device* b_0, uint i_0)
{

#line 146
    return float2(*(b_0+i_0)) ;
}


#line 186
float2 cmulConj_0(float2 a_0, float2 b_1)
{

#line 186
    float _S2 = a_0.x;

#line 186
    float _S3 = b_1.x;

#line 186
    float _S4 = a_0.y;

#line 186
    float _S5 = b_1.y;

#line 186
    return float2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 185
float2 cmul_0(float2 a_1, float2 b_2)
{

#line 185
    float _S6 = a_1.x;

#line 185
    float _S7 = b_2.x;

#line 185
    float _S8 = a_1.y;

#line 185
    float _S9 = b_2.y;

#line 185
    return float2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 335
void r4_0(float2 thread* a_2, float2 thread* b_3, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_2 + *c_0;

#line 337
    float2 t1_0 = *a_2 - *c_0;

#line 337
    float2 t2_0 = *b_3 + *d_0;

#line 337
    float2 t3_0 = *b_3 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_2 = t0_0 + t2_0;

#line 339
    *b_3 = t1_0 + j3_0;

#line 339
    *c_0 = t0_0 - t2_0;

#line 339
    *d_0 = t1_0 - j3_0;
    return;
}


#line 371
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

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

    float2 t_0 = (*r_0)[int(1)];

#line 385
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 385
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 386
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 386
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 387
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 387
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 388
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 388
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 389
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 389
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 390
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 390
    (*r_0)[int(14)] = t_5;
    return;
}


#line 417
void dft32_0(array<float2, int(32)> thread* r_1)
{
    thread array<float2, int(16)> u_0;

#line 419
    thread array<float2, int(16)> v_0;

#line 419
    uint j_0 = 0U;
    for(;;)
    {

#line 420
        if(j_0 < 16U)
        {
        }
        else
        {

#line 420
            break;
        }
        u_0[j_0] = (*r_1)[j_0] + (*r_1)[j_0 + 16U];
        float ang_0 = 6.28318548202514648f * float(j_0) / 32.0f;
        v_0[j_0] = cmul_0((*r_1)[j_0] - (*r_1)[j_0 + 16U], float2(cos(ang_0), sin(ang_0)));

#line 420
        j_0 = j_0 + 1U;

#line 420
    }

#line 426
    dft16_0(&u_0);
    dft16_0(&v_0);

#line 427
    uint k_0 = 0U;
    for(;;)
    {

#line 428
        if(k_0 < 16U)
        {
        }
        else
        {

#line 428
            break;
        }

#line 428
        uint _S11 = 2U * k_0;

#line 428
        (*r_1)[_S11] = u_0[k_0];

#line 428
        (*r_1)[_S11 + 1U] = v_0[k_0];

#line 428
        k_0 = k_0 + 1U;

#line 428
    }
    return;
}


#line 456
void dftR_0(array<float2, int(32)> thread* r_2)
{



    dft32_0(r_2);



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


#line 174 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_32768_refineListed.slang"
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


#line 174
void stgPut_0(uint i_1, float2 v_1, KernelContext_0 thread* kernelContext_0)
{

#line 174
    uint _S12 = 2U * i_1;

#line 174
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S12] = (as_type<uint>((v_1.x)));

#line 174
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S12 + 1U] = (as_type<uint>((v_1.y)));

#line 174
    return;
}


#line 175
float2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 175
    uint _S13 = 2U * i_2;

#line 175
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S13]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S13 + 1U]))));
}


#line 496
void exchange_0(array<float2, int(32)> thread* r_3, const array<uint, int(32)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 496
    uint j_1;

#line 507
    thread array<float2, int(32)> out_0;

#line 507
    uint z_0 = 0U;
    for(;;)
    {

#line 508
        if(z_0 < 32U)
        {
        }
        else
        {

#line 508
            break;
        }

#line 508
        out_0[z_0] = float2(0.0f, 0.0f);

#line 508
        z_0 = z_0 + 1U;

#line 508
    }
    uint _S14 = (1U << lgSpan_0) - 1U;
    uint _S15 = (1U << lgLen_0) - 1U;

#line 510
    uint c_1 = 0U;
    for(;;)
    {

#line 511
        if(c_1 < 4U)
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
        j_1 = 0U;
        for(;;)
        {

#line 513
            if(j_1 < 8U)
            {
            }
            else
            {

#line 513
                break;
            }

#line 513
            stgPut_0(j_1 * 1024U + kernelContext_2->_tid_0, (*r_3)[c_1 * 8U + j_1], kernelContext_2);

#line 513
            j_1 = j_1 + 1U;

#line 513
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 514
        uint d_1 = 0U;
        for(;;)
        {

#line 515
            if(d_1 < 32U)
            {
            }
            else
            {

#line 515
                break;
            }
            uint b_4 = ((*want_0)[d_1]) >> lgLen_0;

#line 517
            uint rem_0 = ((*want_0)[d_1]) & _S15;
            uint i_3 = rem_0 >> lgSpan_0;

#line 518
            uint ln_0 = rem_0 & _S14;
            uint _S16 = c_1 * 8U;

#line 519
            bool _S17;

#line 519
            if(i_3 >= _S16)
            {

#line 519
                _S17 = i_3 < ((c_1 + 1U) * 8U);

#line 519
            }
            else
            {

#line 519
                _S17 = false;

#line 519
            }

#line 519
            if(_S17)
            {

#line 519
                float2 _S18 = stgGet_0((i_3 - _S16) * 1024U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S18;

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
    j_1 = 0U;

#line 523
    for(;;)
    {

#line 523
        if(j_1 < 32U)
        {
        }
        else
        {

#line 523
            break;
        }

#line 523
        (*r_3)[j_1] = out_0[j_1];

#line 523
        j_1 = j_1 + 1U;

#line 523
    }
    return;
}


#line 474
void innermost_0(array<float2, int(32)> thread* r_4)
{

    dft32_0(r_4);

#line 486
    return;
}


#line 578
void transform_0(array<float2, int(32)> thread* r_5, uint tid_0, KernelContext_0 thread* kernelContext_3)
{

#line 578
    uint z_1;

#line 578
    uint _S19;

#line 578
    uint k2_1;

#line 578
    float cr_0;

#line 578
    float ci_0;

#line 578
    uint _S20;

#line 578
    uint d_2;

#line 578
    for(;;)
    {

#line 578
        for(;;)
        {
            for(;;)
            {

#line 581
                thread array<uint, int(32)> want_1;

#line 581
                z_1 = 0U;
                for(;;)
                {

#line 582
                    if(z_1 < 32U)
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



                uint lgTB_0 = firstbithigh_0(1024U);

#line 586
                _S19 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(32768U);

                uint lane_0 = tid_0 & 1023U;

                dftR_0(r_5);

#line 596
                float a1_0 = 6.28318548202514648f * float(lane_0) / 32768.0f;
                float _S21 = cos(a1_0);

#line 597
                float _S22 = sin(a1_0);

#line 597
                k2_1 = 0U;

#line 597
                cr_0 = 1.0f;

#line 597
                ci_0 = 0.0f;

                for(;;)
                {

#line 599
                    if(k2_1 < 32U)
                    {
                    }
                    else
                    {

#line 599
                        break;
                    }

#line 600
                    (*r_5)[k2_1] = cmul_0((*r_5)[k2_1], float2(cr_0, ci_0));
                    float nr_0 = cr_0 * _S21 - ci_0 * _S22;
                    float _S23 = cr_0 * _S22 + ci_0 * _S21;

#line 599
                    k2_1 = k2_1 + 1U;

#line 599
                    cr_0 = nr_0;

#line 599
                    ci_0 = _S23;

#line 599
                }

#line 609
                uint _S24 = max(1024U, 1U);

#line 609
                uint _S25 = 32U / _S24;
                uint _S26 = max(32U, 1U);

#line 610
                _S20 = _S26;
                uint _S27 = tid_0 / _S26;

#line 611
                uint _S28 = tid_0 % _S26;

#line 611
                d_2 = 0U;
                for(;;)
                {

#line 612
                    if(d_2 < 32U)
                    {
                    }
                    else
                    {

#line 612
                        break;
                    }

#line 613
                    uint j_2 = d_2 / _S24;

#line 613
                    uint m_0 = d_2 % _S24;
                    want_1[d_2] = _S27 * 1024U + _S28 + _S26 * d_2;

#line 612
                    d_2 = d_2 + 1U;

#line 612
                }

#line 612
                thread array<uint, int(32)> _S29 = want_1;

#line 612
                exchange_0(r_5, &_S29, lgLn_0, lgTB_0, kernelContext_3);

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
                thread array<uint, int(32)> want_2;

#line 581
                z_1 = 0U;
                for(;;)
                {

#line 582
                    if(z_1 < 32U)
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

                uint _S30 = tid_0 >> lgTB_1;
                uint lane_1 = tid_0 & 31U;

                dftR_0(r_5);

#line 596
                float a1_1 = 6.28318548202514648f * float(lane_1) / 1024.0f;
                float _S31 = cos(a1_1);

#line 597
                float _S32 = sin(a1_1);

#line 597
                k2_1 = 0U;

#line 597
                cr_0 = 1.0f;

#line 597
                ci_0 = 0.0f;

                for(;;)
                {

#line 599
                    if(k2_1 < 32U)
                    {
                    }
                    else
                    {

#line 599
                        break;
                    }

#line 600
                    (*r_5)[k2_1] = cmul_0((*r_5)[k2_1], float2(cr_0, ci_0));
                    float nr_1 = cr_0 * _S31 - ci_0 * _S32;
                    float _S33 = cr_0 * _S32 + ci_0 * _S31;

#line 599
                    k2_1 = k2_1 + 1U;

#line 599
                    cr_0 = nr_1;

#line 599
                    ci_0 = _S33;

#line 599
                }

#line 609
                uint _S34 = 32U / _S20;
                uint _S35 = max(1U, 1U);
                uint _S36 = tid_0 / _S35;

#line 611
                uint _S37 = tid_0 % _S35;

#line 611
                d_2 = 0U;
                for(;;)
                {

#line 612
                    if(d_2 < 32U)
                    {
                    }
                    else
                    {

#line 612
                        break;
                    }

#line 613
                    uint j_3 = d_2 / _S20;

#line 613
                    uint m_1 = d_2 % _S20;
                    want_2[d_2] = _S30 * 1024U + (lane_1 * _S34 + j_3) * 32U + m_1;

#line 612
                    d_2 = d_2 + 1U;

#line 612
                }

#line 612
                thread array<uint, int(32)> _S38 = want_2;

#line 612
                exchange_0(r_5, &_S38, _S19, lgTB_1, kernelContext_3);

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
    uint _S39;

#line 547
    if(i_4 < 2U)
    {

#line 547
        _S39 = 5U;

#line 547
    }
    else
    {

#line 547
        if(i_4 == 2U)
        {

#line 547
            _S39 = 5U;

#line 547
        }
        else
        {

#line 547
            _S39 = 1U;

#line 547
        }

#line 547
    }

#line 547
    return _S39;
}


#line 549
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(2U);

    uint x_0 = slot_0 >> lg_0;

#line 553
    uint lg_1 = lgOf_0(1U);

#line 553
    uint lg_2 = lgOf_0(0U);

#line 558
    return (((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | ((x_0 >> lg_1) & ((1U << lg_2) - 1U));
}


#line 633
void filterPair_0(uint pair_0, uint tid_1, packed_float2 device* data_0, packed_float2 device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint ntmpl_1, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_4)
{


    bool live_0;



    kernelContext_4->_tid_0 = tid_1;
    uint _S40 = pair_0 / ntmpl_1;

#line 642
    uint _S41 = pair_0 % ntmpl_1;

    thread array<float2, int(32)> r_6;

#line 644
    uint n2_0 = 0U;

#line 655
    for(;;)
    {

#line 655
        if(n2_0 < 32U)
        {
        }
        else
        {

#line 655
            break;
        }

#line 656
        uint idx_0 = tid_1 + 1024U * n2_0;
        r_6[n2_0] = cmulConj_0(cload_0(data_0, _S40 * 32768U + idx_0), cload_0(tmpl_0, _S41 * 32768U + idx_0));

#line 655
        n2_0 = n2_0 + 1U;

#line 655
    }

#line 655
    transform_0(&r_6, tid_1, kernelContext_4);

#line 674
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 674
    uint b_5 = tid_1;

#line 682
    for(;;)
    {

#line 682
        if(b_5 < nbins_1)
        {
        }
        else
        {

#line 682
            break;
        }

#line 682
        (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + b_5] = thrBits_1;

#line 682
        b_5 = b_5 + 1024U;

#line 682
    }

    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(32)> myMag_0;
    thread array<uint, int(32)> myBin_0;

#line 687
    uint i_5 = 0U;
    for(;;)
    {

#line 688
        if(i_5 < 32U)
        {
        }
        else
        {

#line 688
            break;
        }

#line 689
        uint idx_1 = slotToIndex_0(tid_1 * 32U + i_5);
        if(idx_1 >= winStart_1)
        {

#line 690
            live_0 = idx_1 < winEnd_1;

#line 690
        }
        else
        {

#line 690
            live_0 = false;

#line 690
        }



        float _rx_0 = r_6[i_5].x;

#line 694
        float _ry_0 = r_6[i_5].y;
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
        uint off_0 = idx_1 - winStart_1;

#line 703
        if(live_0)
        {

#line 703
            if(binShift_1 >= int(0))
            {

#line 703
                b_5 = off_0 >> uint(binShift_1);

#line 703
            }
            else
            {

#line 703
                uint _S42 = off_0 / binsize_1;

#line 703
                b_5 = _S42;

#line 703
            }

#line 703
        }
        else
        {

#line 703
            b_5 = 0U;

#line 703
        }

#line 703
        myBin_0[i_5] = b_5;

#line 703
        bool _S43;



        if(nbins_1 > 1U)
        {

#line 707
            _S43 = (myMag_0[i_5]) > thrBits_1;

#line 707
        }
        else
        {

#line 707
            _S43 = false;

#line 707
        }

#line 707
        if(_S43)
        {

#line 708
            uint _S44 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_5]])), myMag_0[i_5], memory_order_relaxed);

#line 707
        }

#line 688
        i_5 = i_5 + 1U;

#line 688
    }

#line 720
    if(nbins_1 == 1U)
    {

#line 720
        uint bestBits_0 = thrBits_1;

#line 720
        i_5 = 0U;


        for(;;)
        {

#line 723
            if(i_5 < 32U)
            {
            }
            else
            {

#line 723
                break;
            }

#line 723
            uint _S45 = max(bestBits_0, myMag_0[i_5]);

#line 723
            uint i_6 = i_5 + 1U;

#line 723
            bestBits_0 = _S45;

#line 723
            i_5 = i_6;

#line 723
        }

        uint wm_0 = simd_max(bestBits_0);
        bool _S46 = simd_is_first();

#line 726
        if(_S46)
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
            uint _S47 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0])), wm_0, memory_order_relaxed);

#line 726
        }

#line 720
    }

#line 741
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 741
    i_5 = 0U;

#line 746
    for(;;)
    {

#line 746
        if(i_5 < 32U)
        {
        }
        else
        {

#line 746
            break;
        }



        if((myMag_0[i_5]) > thrBits_1)
        {

#line 751
            live_0 = ((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_5]]) == myMag_0[i_5];

#line 751
        }
        else
        {

#line 751
            live_0 = false;

#line 751
        }

#line 751
        if(live_0)
        {

#line 752
            uint o_0 = pair_0 * nbins_1 + myBin_0[i_5];

            *(peakIdx_0+o_0) = int(slotToIndex_0(tid_1 * 32U + i_5));

#line 754
            *(peakVal_0+o_0) = packed_float2(float2(r_6[i_5].x, r_6[i_5].y)) ;

#line 751
        }

#line 746
        i_5 = i_5 + 1U;

#line 746
    }

#line 746
    b_5 = tid_1;

#line 765
    for(;;)
    {

#line 765
        if(b_5 < nbins_1)
        {
        }
        else
        {

#line 765
            break;
        }

#line 766
        if(((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + b_5]) == thrBits_1)
        {

#line 767
            uint o_1 = pair_0 * nbins_1 + b_5;

            *(peakIdx_0+o_1) = int(-1);

#line 769
            *(peakVal_0+o_1) = packed_float2(float2(0.0f, 0.0f)) ;

#line 766
        }

#line 765
        b_5 = b_5 + 1024U;

#line 765
    }

#line 773
    return;
}


#line 1013
[[kernel]] void refineListed(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]], uint device* entryPointParams_survivors_1 [[buffer(5)]])
{

#line 1013
    thread KernelContext_0 kernelContext_5;

#line 1013
    (&kernelContext_5)->entryPointParams_0 = entryPointParams_1;

#line 1013
    (&kernelContext_5)->entryPointParams_data_0 = entryPointParams_data_1;

#line 1013
    (&kernelContext_5)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 1013
    (&kernelContext_5)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 1013
    (&kernelContext_5)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 1013
    (&kernelContext_5)->entryPointParams_survivors_0 = entryPointParams_survivors_1;

#line 1013
    threadgroup array<uint, int(16384)> stg_1;

#line 1013
    (&kernelContext_5)->stg_0 = &stg_1;

#line 1022
    uint pair_1 = entryPointParams_survivors_1[gid_0.x];

#line 1028
    (&kernelContext_5)->_stgBase_0 = 0U;

#line 1028
    filterPair_0(pair_1, lid_0.x, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_5);


    return;
}

