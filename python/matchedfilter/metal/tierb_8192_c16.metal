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
void exchange_0(array<half2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
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
            stgPut_0(j_0 * 512U + kernelContext_2->_tid_0, (*r_1)[c_1 * 16U + j_0], kernelContext_2);

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
        (*r_1)[j_0] = out_0[j_0];

#line 523
        j_0 = j_0 + 1U;

#line 523
    }
    return;
}


#line 346
void dft2_0(array<half2, int(16)> thread* r_2, uint o_0)
{
    half2 a_3 = (*r_2)[o_0];

#line 348
    half2 b_5 = (*r_2)[o_0 + 1U];

#line 348
    (*r_2)[o_0] = (*r_2)[o_0] + (*r_2)[o_0 + 1U];

#line 348
    (*r_2)[o_0 + 1U] = a_3 - b_5;
    return;
}


#line 474
void innermost_0(array<half2, int(16)> thread* r_3)
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
        dft2_0(r_3, b_6 * 2U);

#line 484
        b_6 = b_6 + 1U;

#line 484
    }

    return;
}


#line 578
void transform_0(array<half2, int(16)> thread* r_4, uint tid_0, KernelContext_0 thread* kernelContext_3)
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



                uint lgTB_0 = firstbithigh_0(512U);

#line 13
                _S16 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(8192U);

                uint lane_0 = tid_0 & 511U;


                dft16_0(r_4);

#line 27
                float a1_0 = 6.28318548202514648f * float(lane_0) / 8192.0f;
                float _S20 = cos(a1_0);

#line 28
                float _S21 = sin(a1_0);

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
                    float nr_0 = cr_0 * _S20 - ci_0 * _S21;
                    float _S22 = cr_0 * _S21 + ci_0 * _S20;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_0;

#line 30
                    ci_0 = _S22;

#line 30
                }

#line 40
                uint _S23 = max(512U, 1U);

#line 40
                uint _S24 = 16U / _S23;
                uint _S25 = max(32U, 1U);

#line 41
                _S17 = _S25;
                uint _S26 = tid_0 / _S25;

#line 42
                uint _S27 = tid_0 % _S25;

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
                    uint j_1 = d_2 / _S23;

#line 44
                    uint m_0 = d_2 % _S23;
                    want_1[d_2] = _S26 * 512U + _S27 + _S25 * d_2;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(16)> _S28 = want_1;

#line 43
                exchange_0(r_4, &_S28, lgLn_0, lgTB_0, kernelContext_3);

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



                uint lgTB_1 = firstbithigh_0(32U);

#line 13
                _S18 = lgTB_1;


                uint lane_1 = tid_0 & 31U;


                dft16_0(r_4);

#line 27
                float a1_1 = 6.28318548202514648f * float(lane_1) / 512.0f;
                float _S29 = cos(a1_1);

#line 28
                float _S30 = sin(a1_1);

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
                    float nr_1 = cr_0 * _S29 - ci_0 * _S30;
                    float _S31 = cr_0 * _S30 + ci_0 * _S29;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_1;

#line 30
                    ci_0 = _S31;

#line 30
                }

#line 40
                uint _S32 = 16U / _S17;
                uint _S33 = max(2U, 1U);

#line 41
                _S19 = _S33;
                uint _S34 = tid_0 / _S33;

#line 42
                uint _S35 = tid_0 % _S33;

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
                    want_2[d_2] = _S34 * 32U + _S35 + _S33 * d_2;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(16)> _S36 = want_2;

#line 43
                exchange_0(r_4, &_S36, _S16, lgTB_1, kernelContext_3);

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
                thread array<uint, int(16)> want_3;

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
                    want_3[z_1] = 0U;

#line 9
                    z_1 = z_1 + 1U;

#line 9
                }



                uint lgTB_2 = firstbithigh_0(2U);

                uint _S37 = tid_0 >> lgTB_2;
                uint lane_2 = tid_0 & 1U;


                dft16_0(r_4);

#line 27
                float a1_2 = 6.28318548202514648f * float(lane_2) / 32.0f;
                float _S38 = cos(a1_2);

#line 28
                float _S39 = sin(a1_2);

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
                    float nr_2 = cr_0 * _S38 - ci_0 * _S39;
                    float _S40 = cr_0 * _S39 + ci_0 * _S38;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_2;

#line 30
                    ci_0 = _S40;

#line 30
                }

#line 40
                uint _S41 = 16U / _S19;
                uint _S42 = max(0U, 1U);
                uint _S43 = tid_0 / _S42;

#line 42
                uint _S44 = tid_0 % _S42;

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
                    uint j_3 = d_2 / _S19;

#line 44
                    uint m_2 = d_2 % _S19;
                    want_3[d_2] = _S37 * 32U + (lane_2 * _S41 + j_3) * 2U + m_2;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(16)> _S45 = want_3;

#line 43
                exchange_0(r_4, &_S45, _S18, lgTB_2, kernelContext_3);

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

#line 581 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_8192_fusedTierB_c16.slang"
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


#line 587
void filterOne_0(uint pair_0, uint d_3, uint t_6, uint tid_1, const array<half2, int(16)> thread* dreg_0, uint device* data_0, uint device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_4)
{


    bool live_0;

#line 604
    thread array<half2, int(16)> r_5;

#line 604
    uint n2_0 = 0U;



    for(;;)
    {

#line 608
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 608
            break;
        }

#line 609
        r_5[n2_0] = cmulConj_0((*dreg_0)[n2_0], cload_0(tmpl_0, t_6 * 8192U + tid_1 + 512U * n2_0));

#line 608
        n2_0 = n2_0 + 1U;

#line 608
    }

#line 608
    transform_0(&r_5, tid_1, kernelContext_4);

#line 634
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 640
    bool _S47 = tid_1 == 0U;

#line 640
    if(_S47)
    {

#line 640
        (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0] = thrBits_1;

#line 640
        (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U] = 4294967295U;

#line 640
    }

#line 645
    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;

#line 647
    uint i_5 = 0U;

    for(;;)
    {

#line 649
        if(i_5 < 16U)
        {
        }
        else
        {

#line 649
            break;
        }

#line 650
        uint idx_0 = slotToIndex_0(tid_1 * 16U + i_5);
        if(idx_0 >= winStart_1)
        {

#line 651
            live_0 = idx_0 < winEnd_1;

#line 651
        }
        else
        {

#line 651
            live_0 = false;

#line 651
        }



        float _rx_0 = float(r_5[i_5].x);

#line 655
        float _ry_0 = float(r_5[i_5].y);
        if(live_0)
        {

#line 656
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 656
        }
        else
        {

#line 656
            n2_0 = 0U;

#line 656
        }

#line 656
        myMag_0[i_5] = n2_0;

#line 649
        i_5 = i_5 + 1U;

#line 649
    }

#line 649
    uint bestBits_0 = thrBits_1;

#line 649
    i_5 = 0U;

#line 684
    for(;;)
    {

#line 684
        if(i_5 < 16U)
        {
        }
        else
        {

#line 684
            break;
        }

#line 684
        uint _S48 = max(bestBits_0, myMag_0[i_5]);

#line 684
        uint i_6 = i_5 + 1U;

#line 684
        bestBits_0 = _S48;

#line 684
        i_5 = i_6;

#line 684
    }

    uint wm_0 = simd_max(bestBits_0);
    bool _S49 = simd_is_first();

#line 687
    if(_S49)
    {

#line 687
        live_0 = wm_0 > thrBits_1;

#line 687
    }
    else
    {

#line 687
        live_0 = false;

#line 687
    }

#line 687
    if(live_0)
    {

#line 687
        uint _S50 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0])), wm_0, memory_order_relaxed);

#line 687
    }

#line 702
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 702
    uint winner_0 = 4294967295U;

#line 702
    i_5 = 0U;

#line 712
    for(;;)
    {

#line 712
        if(i_5 < 16U)
        {
        }
        else
        {

#line 712
            break;
        }

#line 713
        if((myMag_0[i_5]) > thrBits_1)
        {

#line 713
            live_0 = (myMag_0[i_5]) == (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0];

#line 713
        }
        else
        {

#line 713
            live_0 = false;

#line 713
        }

#line 713
        if(live_0)
        {

#line 713
            winner_0 = min(winner_0, tid_1 * 16U + i_5);

#line 713
        }

#line 712
        i_5 = i_5 + 1U;

#line 712
    }



    uint waveWinner_0 = simd_min(winner_0);
    bool _S51 = simd_is_first();

#line 717
    if(_S51)
    {

#line 717
        live_0 = waveWinner_0 != 4294967295U;

#line 717
    }
    else
    {

#line 717
        live_0 = false;

#line 717
    }

#line 717
    if(live_0)
    {

#line 718
        uint _S52 = atomic_fetch_min_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U])), waveWinner_0, memory_order_relaxed);

#line 717
    }

#line 722
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 722
    i_5 = 0U;
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

#line 724
        uint _S53 = tid_1 * 16U + i_5;

#line 724
        if(_S53 == (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U])
        {

#line 725
            *(peakIdx_0+pair_0) = int(slotToIndex_0(_S53));

#line 725
            *(peakVal_0+pair_0) = packed_float2(float2(float(r_5[i_5].x), float(r_5[i_5].y))) ;

#line 724
        }

#line 723
        i_5 = i_5 + 1U;

#line 723
    }

#line 729
    if(_S47)
    {

#line 729
        live_0 = ((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U]) == 4294967295U;

#line 729
    }
    else
    {

#line 729
        live_0 = false;

#line 729
    }

#line 729
    if(live_0)
    {

#line 730
        *(peakIdx_0+pair_0) = int(-1);

#line 730
        *(peakVal_0+pair_0) = packed_float2(float2(0.0f, 0.0f)) ;

#line 729
    }

#line 762
    return;
}


#line 901
void filterPair_0(uint pair_1, uint tid_2, uint device* data_1, uint device* tmpl_1, int device* peakIdx_1, packed_float2 device* peakVal_1, uint ntmpl_1, uint winStart_2, uint winEnd_2, uint binsize_2, int binShift_2, uint nbins_2, uint thrBits_2, KernelContext_0 thread* kernelContext_5)
{

#line 907
    kernelContext_5->_tid_0 = tid_2;

#line 917
    uint _S54 = pair_1 / ntmpl_1;

#line 917
    uint _S55 = pair_1 % ntmpl_1;
    thread array<half2, int(16)> dreg_1;

#line 918
    uint n2_1 = 0U;

    for(;;)
    {

#line 920
        if(n2_1 < 16U)
        {
        }
        else
        {

#line 920
            break;
        }

#line 921
        dreg_1[n2_1] = cload_0(data_1, _S54 * 8192U + tid_2 + 512U * n2_1);

#line 920
        n2_1 = n2_1 + 1U;

#line 920
    }

#line 920
    uint k_0 = 0U;

#line 931
    for(;;)
    {

#line 931
        if(k_0 < 1U)
        {
        }
        else
        {

#line 931
            break;
        }

#line 932
        uint _S56 = pair_1 + k_0;

#line 932
        uint _S57 = _S55 + k_0;

#line 932
        thread array<half2, int(16)> _S58 = dreg_1;

#line 932
        filterOne_0(_S56, _S54, _S57, tid_2, &_S58, data_1, tmpl_1, peakIdx_1, peakVal_1, winStart_2, winEnd_2, binsize_2, binShift_2, nbins_2, thrBits_2, kernelContext_5);

#line 931
        k_0 = k_0 + 1U;

#line 931
    }



    return;
}


[[kernel]] void fusedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], uint device* entryPointParams_data_1 [[buffer(1)]], uint device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]])
{

#line 939
    thread KernelContext_0 kernelContext_6;

#line 939
    (&kernelContext_6)->entryPointParams_0 = entryPointParams_1;

#line 939
    (&kernelContext_6)->entryPointParams_data_0 = entryPointParams_data_1;

#line 939
    (&kernelContext_6)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 939
    (&kernelContext_6)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 939
    (&kernelContext_6)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 939
    threadgroup array<uint, int(8192)> stg_1;

#line 939
    (&kernelContext_6)->stg_0 = &stg_1;

#line 956
    uint _pr_0 = gid_0.x;

#line 956
    uint _t_0 = lid_0.x;
    (&kernelContext_6)->_stgBase_0 = 0U;

#line 957
    filterPair_0(_pr_0, _t_0, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_6);

#line 965
    return;
}

