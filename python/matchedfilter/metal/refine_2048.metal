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


#line 146 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_2048_refineListed.slang"
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


#line 335
void r4_0(float2 thread* a_1, float2 thread* b_2, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_1 + *c_0;

#line 337
    float2 t1_0 = *a_1 - *c_0;

#line 337
    float2 t2_0 = *b_2 + *d_0;

#line 337
    float2 t3_0 = *b_2 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
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
float2 cmul_0(float2 a_2, float2 b_3)
{

#line 185
    float _S6 = a_2.x;

#line 185
    float _S7 = b_3.x;

#line 185
    float _S8 = a_2.y;

#line 185
    float _S9 = b_3.y;

#line 185
    return float2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
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


#line 174 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_2048_refineListed.slang"
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
    array<uint, int(4096)> threadgroup* stg_0;
};


#line 174
void stgPut_0(uint i_1, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 174
    uint _S11 = 2U * i_1;

#line 174
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S11] = (as_type<uint>((v_0.x)));

#line 174
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S11 + 1U] = (as_type<uint>((v_0.y)));

#line 174
    return;
}


#line 175
float2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 175
    uint _S12 = 2U * i_2;

#line 175
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S12]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S12 + 1U]))));
}


#line 496
void exchange_0(array<float2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 496
    uint j_0;

#line 507
    thread array<float2, int(16)> out_0;

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
        out_0[z_0] = float2(0.0f, 0.0f);

#line 508
        z_0 = z_0 + 1U;

#line 508
    }
    uint _S13 = (1U << lgSpan_0) - 1U;
    uint _S14 = (1U << lgLen_0) - 1U;

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
            stgPut_0(j_0 * 128U + kernelContext_2->_tid_0, (*r_1)[c_1 * 16U + j_0], kernelContext_2);

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
            uint rem_0 = ((*want_0)[d_1]) & _S14;
            uint i_3 = rem_0 >> lgSpan_0;

#line 518
            uint ln_0 = rem_0 & _S13;
            uint _S15 = c_1 * 16U;

#line 519
            bool _S16;

#line 519
            if(i_3 >= _S15)
            {

#line 519
                _S16 = i_3 < ((c_1 + 1U) * 16U);

#line 519
            }
            else
            {

#line 519
                _S16 = false;

#line 519
            }

#line 519
            if(_S16)
            {

#line 519
                float2 _S17 = stgGet_0((i_3 - _S15) * 128U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S17;

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


#line 355
void dft8_0(array<float2, int(16)> thread* r_2, uint o_0)
{


    thread array<float2, int(8)> b_5;

#line 359
    uint s_0 = 1U;
    for(;;)
    {

#line 360
        if(s_0 < 8U)
        {
        }
        else
        {

#line 360
            break;
        }

#line 360
        uint j_1 = 0U;
        for(;;)
        {

#line 361
            if(j_1 < 4U)
            {
            }
            else
            {

#line 361
                break;
            }

#line 362
            uint k_0 = j_1 & (s_0 - 1U);
            float ang_0 = 3.14159274101257324f * float(k_0) / float(s_0);

            uint _S18 = o_0 + j_1;

#line 365
            float2 t_6 = cmul_0(float2(cos(ang_0), sin(ang_0)), (*r_2)[_S18 + 4U]);
            uint _S19 = ((j_1 - k_0) << 1U) + k_0;

#line 366
            b_5[_S19] = (*r_2)[_S18] + t_6;

#line 366
            b_5[_S19 + s_0] = (*r_2)[_S18] - t_6;

#line 361
            j_1 = j_1 + 1U;

#line 361
        }

#line 361
        uint i_4 = 0U;

#line 368
        for(;;)
        {

#line 368
            if(i_4 < 8U)
            {
            }
            else
            {

#line 368
                break;
            }

#line 368
            (*r_2)[o_0 + i_4] = b_5[i_4];

#line 368
            i_4 = i_4 + 1U;

#line 368
        }

#line 360
        s_0 = s_0 << 1U;

#line 360
    }

#line 370
    return;
}


#line 474
void innermost_0(array<float2, int(16)> thread* r_3)
{

#line 474
    uint b_6 = 0U;

#line 482
    for(;;)
    {

#line 482
        if(b_6 < 2U)
        {
        }
        else
        {

#line 482
            break;
        }

#line 482
        dft8_0(r_3, b_6 * 8U);

#line 482
        b_6 = b_6 + 1U;

#line 482
    }



    return;
}


#line 578
void transform_0(array<float2, int(16)> thread* r_4, uint tid_0, KernelContext_0 thread* kernelContext_3)
{

#line 578
    uint z_1;

#line 578
    uint _S20;

#line 578
    uint k2_1;

#line 578
    float cr_0;

#line 578
    float ci_0;

#line 578
    uint _S21;

#line 578
    uint d_2;

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



                uint lgTB_0 = firstbithigh_0(128U);

#line 13
                _S20 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(2048U);

                uint lane_0 = tid_0 & 127U;


                dft16_0(r_4);

#line 27
                float a1_0 = 6.28318548202514648f * float(lane_0) / 2048.0f;
                float _S22 = cos(a1_0);

#line 28
                float _S23 = sin(a1_0);

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
                    (*r_4)[k2_1] = cmul_0((*r_4)[k2_1], float2(cr_0, ci_0));
                    float nr_0 = cr_0 * _S22 - ci_0 * _S23;
                    float _S24 = cr_0 * _S23 + ci_0 * _S22;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_0;

#line 30
                    ci_0 = _S24;

#line 30
                }

#line 40
                uint _S25 = max(128U, 1U);

#line 40
                uint _S26 = 16U / _S25;
                uint _S27 = max(8U, 1U);

#line 41
                _S21 = _S27;
                uint _S28 = tid_0 / _S27;

#line 42
                uint _S29 = tid_0 % _S27;

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
                    uint j_2 = d_2 / _S25;

#line 44
                    uint m_0 = d_2 % _S25;
                    want_1[d_2] = _S28 * 128U + _S29 + _S27 * d_2;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(16)> _S30 = want_1;

#line 43
                exchange_0(r_4, &_S30, lgLn_0, lgTB_0, kernelContext_3);

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



                uint lgTB_1 = firstbithigh_0(8U);

                uint _S31 = tid_0 >> lgTB_1;
                uint lane_1 = tid_0 & 7U;


                dft16_0(r_4);

#line 27
                float a1_1 = 6.28318548202514648f * float(lane_1) / 128.0f;
                float _S32 = cos(a1_1);

#line 28
                float _S33 = sin(a1_1);

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
                    (*r_4)[k2_1] = cmul_0((*r_4)[k2_1], float2(cr_0, ci_0));
                    float nr_1 = cr_0 * _S32 - ci_0 * _S33;
                    float _S34 = cr_0 * _S33 + ci_0 * _S32;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_1;

#line 30
                    ci_0 = _S34;

#line 30
                }

#line 40
                uint _S35 = 16U / _S21;
                uint _S36 = max(0U, 1U);
                uint _S37 = tid_0 / _S36;

#line 42
                uint _S38 = tid_0 % _S36;

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
                    uint j_3 = d_2 / _S21;

#line 44
                    uint m_1 = d_2 % _S21;
                    want_2[d_2] = _S31 * 128U + (lane_1 * _S35 + j_3) * 8U + m_1;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(16)> _S39 = want_2;

#line 43
                exchange_0(r_4, &_S39, _S20, lgTB_1, kernelContext_3);

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

#line 581 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_2048_refineListed.slang"
    return;
}


#line 547
uint lgOf_0(uint i_5)
{

#line 547
    uint _S40;

#line 547
    if(i_5 < 2U)
    {

#line 547
        _S40 = 4U;

#line 547
    }
    else
    {

#line 547
        if(i_5 == 2U)
        {

#line 547
            _S40 = 3U;

#line 547
        }
        else
        {

#line 547
            _S40 = 1U;

#line 547
        }

#line 547
    }

#line 547
    return _S40;
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


#line 593
void filterPair_0(uint pair_0, uint tid_1, packed_float2 device* data_0, packed_float2 device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint ntmpl_1, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_4)
{

#line 601
    kernelContext_4->_tid_0 = tid_1;
    uint _S41 = pair_0 / ntmpl_1;

#line 602
    uint _S42 = pair_0 % ntmpl_1;

    thread array<float2, int(16)> r_5;

#line 604
    uint n2_0 = 0U;

#line 615
    for(;;)
    {

#line 615
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 615
            break;
        }

#line 616
        uint idx_0 = tid_1 + 128U * n2_0;
        r_5[n2_0] = cmulConj_0(cload_0(data_0, _S41 * 2048U + idx_0), cload_0(tmpl_0, _S42 * 2048U + idx_0));

#line 615
        n2_0 = n2_0 + 1U;

#line 615
    }

#line 615
    transform_0(&r_5, tid_1, kernelContext_4);

#line 634
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 634
    uint b_7 = tid_1;

#line 642
    for(;;)
    {

#line 642
        if(b_7 < nbins_1)
        {
        }
        else
        {

#line 642
            break;
        }

#line 642
        (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + b_7] = thrBits_1;

#line 642
        b_7 = b_7 + 128U;

#line 642
    }
    bool _S43 = nbins_1 == 1U;

#line 643
    bool live_0;

#line 643
    if(_S43)
    {

#line 643
        live_0 = tid_1 == 0U;

#line 643
    }
    else
    {

#line 643
        live_0 = false;

#line 643
    }

#line 643
    if(live_0)
    {

#line 643
        (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U] = 4294967295U;

#line 643
    }

    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;
    thread array<uint, int(16)> myBin_0;

#line 648
    uint i_6 = 0U;
    for(;;)
    {

#line 649
        if(i_6 < 16U)
        {
        }
        else
        {

#line 649
            break;
        }

#line 650
        uint idx_1 = slotToIndex_0(tid_1 * 16U + i_6);
        if(idx_1 >= winStart_1)
        {

#line 651
            live_0 = idx_1 < winEnd_1;

#line 651
        }
        else
        {

#line 651
            live_0 = false;

#line 651
        }



        float _rx_0 = r_5[i_6].x;

#line 655
        float _ry_0 = r_5[i_6].y;
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
        myMag_0[i_6] = n2_0;
        uint off_0 = idx_1 - winStart_1;

#line 664
        if(live_0)
        {

#line 664
            if(binShift_1 >= int(0))
            {

#line 664
                b_7 = off_0 >> uint(binShift_1);

#line 664
            }
            else
            {

#line 664
                uint _S44 = off_0 / binsize_1;

#line 664
                b_7 = _S44;

#line 664
            }

#line 664
        }
        else
        {

#line 664
            b_7 = 0U;

#line 664
        }

#line 664
        myBin_0[i_6] = b_7;

#line 664
        bool _S45;



        if(nbins_1 > 1U)
        {

#line 668
            _S45 = (myMag_0[i_6]) > thrBits_1;

#line 668
        }
        else
        {

#line 668
            _S45 = false;

#line 668
        }

#line 668
        if(_S45)
        {

#line 669
            uint _S46 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_6]])), myMag_0[i_6], memory_order_relaxed);

#line 668
        }

#line 649
        i_6 = i_6 + 1U;

#line 649
    }

#line 649
    uint winner_0;

#line 681
    if(_S43)
    {

#line 681
        winner_0 = thrBits_1;

#line 681
        i_6 = 0U;


        for(;;)
        {

#line 684
            if(i_6 < 16U)
            {
            }
            else
            {

#line 684
                break;
            }

#line 684
            uint _S47 = max(winner_0, myMag_0[i_6]);

#line 684
            uint i_7 = i_6 + 1U;

#line 684
            winner_0 = _S47;

#line 684
            i_6 = i_7;

#line 684
        }

        uint wm_0 = simd_max(winner_0);
        bool _S48 = simd_is_first();

#line 687
        if(_S48)
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
            uint _S49 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0])), wm_0, memory_order_relaxed);

#line 687
        }

#line 681
    }

#line 702
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 709
    if(_S43)
    {

#line 709
        winner_0 = 4294967295U;

#line 709
        i_6 = 0U;


        for(;;)
        {

#line 712
            if(i_6 < 16U)
            {
            }
            else
            {

#line 712
                break;
            }

#line 713
            if((myMag_0[i_6]) > thrBits_1)
            {

#line 713
                live_0 = (myMag_0[i_6]) == (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0];

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
                winner_0 = min(winner_0, tid_1 * 16U + i_6);

#line 713
            }

#line 712
            i_6 = i_6 + 1U;

#line 712
        }



        uint waveWinner_0 = simd_min(winner_0);
        bool _S50 = simd_is_first();

#line 717
        if(_S50)
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
            uint _S51 = atomic_fetch_min_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U])), waveWinner_0, memory_order_relaxed);

#line 717
        }

#line 722
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 722
        i_6 = 0U;
        for(;;)
        {

#line 723
            if(i_6 < 16U)
            {
            }
            else
            {

#line 723
                break;
            }

#line 724
            uint _S52 = tid_1 * 16U + i_6;

#line 724
            if(_S52 == (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U])
            {

#line 725
                *(peakIdx_0+pair_0) = int(slotToIndex_0(_S52));

#line 725
                *(peakVal_0+pair_0) = packed_float2(float2(r_5[i_6].x, r_5[i_6].y)) ;

#line 724
            }

#line 723
            i_6 = i_6 + 1U;

#line 723
        }

#line 729
        if(tid_1 == 0U)
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

#line 709
    }
    else
    {

#line 709
        i_6 = 0U;

#line 738
        for(;;)
        {

#line 738
            if(i_6 < 16U)
            {
            }
            else
            {

#line 738
                break;
            }

#line 739
            if((myMag_0[i_6]) > thrBits_1)
            {

#line 739
                live_0 = (myMag_0[i_6]) == (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_6]];

#line 739
            }
            else
            {

#line 739
                live_0 = false;

#line 739
            }

#line 739
            myMag_0[i_6] = uint(live_0);

#line 738
            i_6 = i_6 + 1U;

#line 738
        }


        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 741
        b_7 = tid_1;
        for(;;)
        {

#line 742
            if(b_7 < nbins_1)
            {
            }
            else
            {

#line 742
                break;
            }

#line 742
            (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + b_7] = 4294967295U;

#line 742
            b_7 = b_7 + 128U;

#line 742
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 743
        i_6 = 0U;
        for(;;)
        {

#line 744
            if(i_6 < 16U)
            {
            }
            else
            {

#line 744
                break;
            }

#line 745
            if((myMag_0[i_6]) != 0U)
            {

#line 745
                uint _S53 = atomic_fetch_min_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_6]])), tid_1 * 16U + i_6, memory_order_relaxed);

#line 745
            }

#line 744
            i_6 = i_6 + 1U;

#line 744
        }

        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 746
        i_6 = 0U;
        for(;;)
        {

#line 747
            if(i_6 < 16U)
            {
            }
            else
            {

#line 747
                break;
            }

#line 748
            if((myMag_0[i_6]) != 0U)
            {

#line 748
                live_0 = ((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_6]]) == (tid_1 * 16U + i_6);

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

#line 749
                uint o_1 = pair_0 * nbins_1 + myBin_0[i_6];
                *(peakIdx_0+o_1) = int(slotToIndex_0(tid_1 * 16U + i_6));

#line 750
                *(peakVal_0+o_1) = packed_float2(float2(r_5[i_6].x, r_5[i_6].y)) ;

#line 748
            }

#line 747
            i_6 = i_6 + 1U;

#line 747
        }

#line 747
        b_7 = tid_1;

#line 754
        for(;;)
        {

#line 754
            if(b_7 < nbins_1)
            {
            }
            else
            {

#line 754
                break;
            }

#line 755
            if(((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + b_7]) == 4294967295U)
            {

#line 756
                uint _S54 = pair_0 * nbins_1 + b_7;

#line 756
                *(peakIdx_0+_S54) = int(-1);

#line 756
                *(peakVal_0+_S54) = packed_float2(float2(0.0f, 0.0f)) ;

#line 755
            }

#line 754
            b_7 = b_7 + 128U;

#line 754
        }

#line 709
    }

#line 762
    return;
}


#line 1015
[[kernel]] void refineListed(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]], uint device* entryPointParams_survivors_1 [[buffer(5)]])
{

#line 1015
    thread KernelContext_0 kernelContext_5;

#line 1015
    (&kernelContext_5)->entryPointParams_0 = entryPointParams_1;

#line 1015
    (&kernelContext_5)->entryPointParams_data_0 = entryPointParams_data_1;

#line 1015
    (&kernelContext_5)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 1015
    (&kernelContext_5)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 1015
    (&kernelContext_5)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 1015
    (&kernelContext_5)->entryPointParams_survivors_0 = entryPointParams_survivors_1;

#line 1015
    threadgroup array<uint, int(4096)> stg_1;

#line 1015
    (&kernelContext_5)->stg_0 = &stg_1;

#line 1024
    uint pair_1 = entryPointParams_survivors_1[gid_0.x];

#line 1030
    (&kernelContext_5)->_stgBase_0 = 0U;

#line 1030
    filterPair_0(pair_1, lid_0.x, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_5);


    return;
}

