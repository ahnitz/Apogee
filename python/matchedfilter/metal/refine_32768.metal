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


#line 149 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_32768_refineListed.slang"
float2 cload_0(packed_float2 device* b_0, uint i_0)
{

#line 149
    return float2(*(b_0+i_0)) ;
}


#line 189
float2 cmulConj_0(float2 a_0, float2 b_1)
{

#line 189
    float _S2 = a_0.x;

#line 189
    float _S3 = b_1.x;

#line 189
    float _S4 = a_0.y;

#line 189
    float _S5 = b_1.y;

#line 189
    return float2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 188
float2 cmul_0(float2 a_1, float2 b_2)
{

#line 188
    float _S6 = a_1.x;

#line 188
    float _S7 = b_2.x;

#line 188
    float _S8 = a_1.y;

#line 188
    float _S9 = b_2.y;

#line 188
    return float2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 338
void r4_0(float2 thread* a_2, float2 thread* b_3, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_2 + *c_0;

#line 340
    float2 t1_0 = *a_2 - *c_0;

#line 340
    float2 t2_0 = *b_3 + *d_0;

#line 340
    float2 t3_0 = *b_3 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_2 = t0_0 + t2_0;

#line 342
    *b_3 = t1_0 + j3_0;

#line 342
    *c_0 = t0_0 - t2_0;

#line 342
    *d_0 = t1_0 - j3_0;
    return;
}


#line 374
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

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

    float2 t_0 = (*r_0)[int(1)];

#line 388
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 388
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 389
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 389
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 390
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 390
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 391
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 391
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 392
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 392
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 393
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 393
    (*r_0)[int(14)] = t_5;
    return;
}


#line 420
void dft32_0(array<float2, int(32)> thread* r_1)
{
    thread array<float2, int(16)> u_0;

#line 422
    thread array<float2, int(16)> v_0;

#line 422
    uint j_0 = 0U;
    for(;;)
    {

#line 423
        if(j_0 < 16U)
        {
        }
        else
        {

#line 423
            break;
        }
        u_0[j_0] = (*r_1)[j_0] + (*r_1)[j_0 + 16U];
        float ang_0 = 6.28318548202514648f * float(j_0) / 32.0f;
        v_0[j_0] = cmul_0((*r_1)[j_0] - (*r_1)[j_0 + 16U], float2(cos(ang_0), sin(ang_0)));

#line 423
        j_0 = j_0 + 1U;

#line 423
    }

#line 429
    dft16_0(&u_0);
    dft16_0(&v_0);

#line 430
    uint k_0 = 0U;
    for(;;)
    {

#line 431
        if(k_0 < 16U)
        {
        }
        else
        {

#line 431
            break;
        }

#line 431
        uint _S11 = 2U * k_0;

#line 431
        (*r_1)[_S11] = u_0[k_0];

#line 431
        (*r_1)[_S11 + 1U] = v_0[k_0];

#line 431
        k_0 = k_0 + 1U;

#line 431
    }
    return;
}


#line 459
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


#line 177 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_32768_refineListed.slang"
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


#line 177
void stgPut_0(uint i_1, float2 v_1, KernelContext_0 thread* kernelContext_0)
{

#line 177
    uint _S12 = 2U * i_1;

#line 177
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S12] = (as_type<uint>((v_1.x)));

#line 177
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S12 + 1U] = (as_type<uint>((v_1.y)));

#line 177
    return;
}


#line 178
float2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 178
    uint _S13 = 2U * i_2;

#line 178
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S13]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S13 + 1U]))));
}


#line 499
void exchange_0(array<float2, int(32)> thread* r_3, const array<uint, int(32)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 499
    uint j_1;

#line 510
    thread array<float2, int(32)> out_0;

#line 510
    uint z_0 = 0U;
    for(;;)
    {

#line 511
        if(z_0 < 32U)
        {
        }
        else
        {

#line 511
            break;
        }

#line 511
        out_0[z_0] = float2(0.0f, 0.0f);

#line 511
        z_0 = z_0 + 1U;

#line 511
    }
    uint _S14 = (1U << lgSpan_0) - 1U;
    uint _S15 = (1U << lgLen_0) - 1U;

#line 513
    uint c_1 = 0U;
    for(;;)
    {

#line 514
        if(c_1 < 4U)
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
        j_1 = 0U;
        for(;;)
        {

#line 516
            if(j_1 < 8U)
            {
            }
            else
            {

#line 516
                break;
            }

#line 516
            stgPut_0(j_1 * 1024U + kernelContext_2->_tid_0, (*r_3)[c_1 * 8U + j_1], kernelContext_2);

#line 516
            j_1 = j_1 + 1U;

#line 516
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 517
        uint d_1 = 0U;
        for(;;)
        {

#line 518
            if(d_1 < 32U)
            {
            }
            else
            {

#line 518
                break;
            }
            uint b_4 = ((*want_0)[d_1]) >> lgLen_0;

#line 520
            uint rem_0 = ((*want_0)[d_1]) & _S15;
            uint i_3 = rem_0 >> lgSpan_0;

#line 521
            uint ln_0 = rem_0 & _S14;
            uint _S16 = c_1 * 8U;

#line 522
            bool _S17;

#line 522
            if(i_3 >= _S16)
            {

#line 522
                _S17 = i_3 < ((c_1 + 1U) * 8U);

#line 522
            }
            else
            {

#line 522
                _S17 = false;

#line 522
            }

#line 522
            if(_S17)
            {

#line 522
                float2 _S18 = stgGet_0((i_3 - _S16) * 1024U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S18;

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
    j_1 = 0U;

#line 526
    for(;;)
    {

#line 526
        if(j_1 < 32U)
        {
        }
        else
        {

#line 526
            break;
        }

#line 526
        (*r_3)[j_1] = out_0[j_1];

#line 526
        j_1 = j_1 + 1U;

#line 526
    }
    return;
}


#line 477
void innermost_0(array<float2, int(32)> thread* r_4)
{

    dft32_0(r_4);

#line 489
    return;
}


#line 581
void transform_0(array<float2, int(32)> thread* r_5, uint tid_0, KernelContext_0 thread* kernelContext_3)
{

#line 581
    uint z_1;

#line 581
    uint _S19;

#line 581
    uint k2_1;

#line 581
    float cr_0;

#line 581
    float ci_0;

#line 581
    uint _S20;

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
                thread array<uint, int(32)> want_1;

#line 8
                z_1 = 0U;
                for(;;)
                {

#line 9
                    if(z_1 < 32U)
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



                uint lgTB_0 = firstbithigh_0(1024U);

#line 13
                _S19 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(32768U);

                uint lane_0 = tid_0 & 1023U;

#line 21
                dftR_0(r_5);

#line 27
                float a1_0 = 6.28318548202514648f * float(lane_0) / 32768.0f;
                float _S21 = cos(a1_0);

#line 28
                float _S22 = sin(a1_0);

#line 28
                k2_1 = 0U;

#line 28
                cr_0 = 1.0f;

#line 28
                ci_0 = 0.0f;

                for(;;)
                {

#line 30
                    if(k2_1 < 32U)
                    {
                    }
                    else
                    {

#line 30
                        break;
                    }

#line 31
                    (*r_5)[k2_1] = cmul_0((*r_5)[k2_1], float2(cr_0, ci_0));
                    float nr_0 = cr_0 * _S21 - ci_0 * _S22;
                    float _S23 = cr_0 * _S22 + ci_0 * _S21;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_0;

#line 30
                    ci_0 = _S23;

#line 30
                }

#line 40
                uint _S24 = max(1024U, 1U);

#line 40
                uint _S25 = 32U / _S24;
                uint _S26 = max(32U, 1U);

#line 41
                _S20 = _S26;
                uint _S27 = tid_0 / _S26;

#line 42
                uint _S28 = tid_0 % _S26;

#line 42
                d_2 = 0U;
                for(;;)
                {

#line 43
                    if(d_2 < 32U)
                    {
                    }
                    else
                    {

#line 43
                        break;
                    }

#line 44
                    uint j_2 = d_2 / _S24;

#line 44
                    uint m_0 = d_2 % _S24;
                    want_1[d_2] = _S27 * 1024U + _S28 + _S26 * d_2;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(32)> _S29 = want_1;

#line 43
                exchange_0(r_5, &_S29, lgLn_0, lgTB_0, kernelContext_3);

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
                thread array<uint, int(32)> want_2;

#line 8
                z_1 = 0U;
                for(;;)
                {

#line 9
                    if(z_1 < 32U)
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

                uint _S30 = tid_0 >> lgTB_1;
                uint lane_1 = tid_0 & 31U;

#line 21
                dftR_0(r_5);

#line 27
                float a1_1 = 6.28318548202514648f * float(lane_1) / 1024.0f;
                float _S31 = cos(a1_1);

#line 28
                float _S32 = sin(a1_1);

#line 28
                k2_1 = 0U;

#line 28
                cr_0 = 1.0f;

#line 28
                ci_0 = 0.0f;

                for(;;)
                {

#line 30
                    if(k2_1 < 32U)
                    {
                    }
                    else
                    {

#line 30
                        break;
                    }

#line 31
                    (*r_5)[k2_1] = cmul_0((*r_5)[k2_1], float2(cr_0, ci_0));
                    float nr_1 = cr_0 * _S31 - ci_0 * _S32;
                    float _S33 = cr_0 * _S32 + ci_0 * _S31;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_1;

#line 30
                    ci_0 = _S33;

#line 30
                }

#line 40
                uint _S34 = 32U / _S20;
                uint _S35 = max(1U, 1U);
                uint _S36 = tid_0 / _S35;

#line 42
                uint _S37 = tid_0 % _S35;

#line 42
                d_2 = 0U;
                for(;;)
                {

#line 43
                    if(d_2 < 32U)
                    {
                    }
                    else
                    {

#line 43
                        break;
                    }

#line 44
                    uint j_3 = d_2 / _S20;

#line 44
                    uint m_1 = d_2 % _S20;
                    want_2[d_2] = _S30 * 1024U + (lane_1 * _S34 + j_3) * 32U + m_1;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(32)> _S38 = want_2;

#line 43
                exchange_0(r_5, &_S38, _S19, lgTB_1, kernelContext_3);

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
    innermost_0(r_5);

#line 584 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_32768_refineListed.slang"
    return;
}


#line 550
uint lgOf_0(uint i_4)
{

#line 550
    uint _S39;

#line 550
    if(i_4 < 2U)
    {

#line 550
        _S39 = 5U;

#line 550
    }
    else
    {

#line 550
        if(i_4 == 2U)
        {

#line 550
            _S39 = 5U;

#line 550
        }
        else
        {

#line 550
            _S39 = 1U;

#line 550
        }

#line 550
    }

#line 550
    return _S39;
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


#line 596
void filterPair_0(uint pair_0, uint tid_1, packed_float2 device* data_0, packed_float2 device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint ntmpl_1, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_4)
{

#line 610
    kernelContext_4->_tid_0 = tid_1;
    uint _S40 = pair_0 / ntmpl_1;

#line 611
    uint _S41 = pair_0 % ntmpl_1;

    thread array<float2, int(32)> r_6;

#line 613
    uint n2_0 = 0U;

#line 624
    for(;;)
    {

#line 624
        if(n2_0 < 32U)
        {
        }
        else
        {

#line 624
            break;
        }

#line 625
        uint idx_0 = tid_1 + 1024U * n2_0;
        r_6[n2_0] = cmulConj_0(cload_0(data_0, _S40 * 32768U + idx_0), cload_0(tmpl_0, _S41 * 32768U + idx_0));

#line 624
        n2_0 = n2_0 + 1U;

#line 624
    }

#line 624
    transform_0(&r_6, tid_1, kernelContext_4);

#line 643
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 643
    uint b_5 = tid_1;

#line 651
    for(;;)
    {

#line 651
        if(b_5 < nbins_1)
        {
        }
        else
        {

#line 651
            break;
        }

#line 651
        (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + b_5] = thrBits_1;

#line 651
        b_5 = b_5 + 1024U;

#line 651
    }
    bool _S42 = nbins_1 == 1U;

#line 652
    bool live_0;

#line 652
    if(_S42)
    {

#line 652
        live_0 = tid_1 == 0U;

#line 652
    }
    else
    {

#line 652
        live_0 = false;

#line 652
    }

#line 652
    if(live_0)
    {

#line 652
        (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U] = 4294967295U;

#line 652
    }

    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(32)> myMag_0;
    thread array<uint, int(32)> myBin_0;

#line 657
    uint i_5 = 0U;
    for(;;)
    {

#line 658
        if(i_5 < 32U)
        {
        }
        else
        {

#line 658
            break;
        }

#line 659
        uint idx_1 = slotToIndex_0(tid_1 * 32U + i_5);
        if(idx_1 >= winStart_1)
        {

#line 660
            live_0 = idx_1 < winEnd_1;

#line 660
        }
        else
        {

#line 660
            live_0 = false;

#line 660
        }



        float _rx_0 = r_6[i_5].x;

#line 664
        float _ry_0 = r_6[i_5].y;
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
        uint off_0 = idx_1 - winStart_1;

#line 673
        if(live_0)
        {

#line 673
            if(binShift_1 >= int(0))
            {

#line 673
                b_5 = off_0 >> uint(binShift_1);

#line 673
            }
            else
            {

#line 673
                uint _S43 = off_0 / binsize_1;

#line 673
                b_5 = _S43;

#line 673
            }

#line 673
        }
        else
        {

#line 673
            b_5 = 0U;

#line 673
        }

#line 673
        myBin_0[i_5] = b_5;

#line 673
        bool _S44;



        if(nbins_1 > 1U)
        {

#line 677
            _S44 = (myMag_0[i_5]) > thrBits_1;

#line 677
        }
        else
        {

#line 677
            _S44 = false;

#line 677
        }

#line 677
        if(_S44)
        {

#line 678
            uint _S45 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_5]])), myMag_0[i_5], memory_order_relaxed);

#line 677
        }

#line 658
        i_5 = i_5 + 1U;

#line 658
    }

#line 658
    uint winner_0;

#line 690
    if(_S42)
    {

#line 690
        winner_0 = thrBits_1;

#line 690
        i_5 = 0U;


        for(;;)
        {

#line 693
            if(i_5 < 32U)
            {
            }
            else
            {

#line 693
                break;
            }

#line 693
            uint _S46 = max(winner_0, myMag_0[i_5]);

#line 693
            uint i_6 = i_5 + 1U;

#line 693
            winner_0 = _S46;

#line 693
            i_5 = i_6;

#line 693
        }

        uint wm_0 = simd_max(winner_0);
        bool _S47 = simd_is_first();

#line 696
        if(_S47)
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
            uint _S48 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0])), wm_0, memory_order_relaxed);

#line 696
        }

#line 690
    }

#line 711
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 718
    if(_S42)
    {

#line 718
        winner_0 = 4294967295U;

#line 718
        i_5 = 0U;


        for(;;)
        {

#line 721
            if(i_5 < 32U)
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
                winner_0 = min(winner_0, tid_1 * 32U + i_5);

#line 722
            }

#line 721
            i_5 = i_5 + 1U;

#line 721
        }



        uint waveWinner_0 = simd_min(winner_0);
        bool _S49 = simd_is_first();

#line 726
        if(_S49)
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
            uint _S50 = atomic_fetch_min_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U])), waveWinner_0, memory_order_relaxed);

#line 726
        }

#line 731
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 731
        i_5 = 0U;
        for(;;)
        {

#line 732
            if(i_5 < 32U)
            {
            }
            else
            {

#line 732
                break;
            }

#line 733
            uint _S51 = tid_1 * 32U + i_5;

#line 733
            if(_S51 == (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U])
            {

#line 734
                *(peakIdx_0+pair_0) = int(slotToIndex_0(_S51));

#line 734
                *(peakVal_0+pair_0) = packed_float2(float2(r_6[i_5].x, r_6[i_5].y)) ;

#line 733
            }

#line 732
            i_5 = i_5 + 1U;

#line 732
        }

#line 738
        if(tid_1 == 0U)
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

#line 718
    }
    else
    {

#line 718
        i_5 = 0U;

#line 747
        for(;;)
        {

#line 747
            if(i_5 < 32U)
            {
            }
            else
            {

#line 747
                break;
            }

#line 748
            if((myMag_0[i_5]) > thrBits_1)
            {

#line 748
                live_0 = (myMag_0[i_5]) == (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_5]];

#line 748
            }
            else
            {

#line 748
                live_0 = false;

#line 748
            }

#line 748
            myMag_0[i_5] = uint(live_0);

#line 747
            i_5 = i_5 + 1U;

#line 747
        }


        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 750
        b_5 = tid_1;
        for(;;)
        {

#line 751
            if(b_5 < nbins_1)
            {
            }
            else
            {

#line 751
                break;
            }

#line 751
            (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + b_5] = 4294967295U;

#line 751
            b_5 = b_5 + 1024U;

#line 751
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 752
        i_5 = 0U;
        for(;;)
        {

#line 753
            if(i_5 < 32U)
            {
            }
            else
            {

#line 753
                break;
            }

#line 754
            if((myMag_0[i_5]) != 0U)
            {

#line 754
                uint _S52 = atomic_fetch_min_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_5]])), tid_1 * 32U + i_5, memory_order_relaxed);

#line 754
            }

#line 753
            i_5 = i_5 + 1U;

#line 753
        }

        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 755
        i_5 = 0U;
        for(;;)
        {

#line 756
            if(i_5 < 32U)
            {
            }
            else
            {

#line 756
                break;
            }

#line 757
            if((myMag_0[i_5]) != 0U)
            {

#line 757
                live_0 = ((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_5]]) == (tid_1 * 32U + i_5);

#line 757
            }
            else
            {

#line 757
                live_0 = false;

#line 757
            }

#line 757
            if(live_0)
            {

#line 758
                uint o_0 = pair_0 * nbins_1 + myBin_0[i_5];
                *(peakIdx_0+o_0) = int(slotToIndex_0(tid_1 * 32U + i_5));

#line 759
                *(peakVal_0+o_0) = packed_float2(float2(r_6[i_5].x, r_6[i_5].y)) ;

#line 757
            }

#line 756
            i_5 = i_5 + 1U;

#line 756
        }

#line 756
        b_5 = tid_1;

#line 763
        for(;;)
        {

#line 763
            if(b_5 < nbins_1)
            {
            }
            else
            {

#line 763
                break;
            }

#line 764
            if(((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + b_5]) == 4294967295U)
            {

#line 765
                uint _S53 = pair_0 * nbins_1 + b_5;

#line 765
                *(peakIdx_0+_S53) = int(-1);

#line 765
                *(peakVal_0+_S53) = packed_float2(float2(0.0f, 0.0f)) ;

#line 764
            }

#line 763
            b_5 = b_5 + 1024U;

#line 763
        }

#line 718
    }

#line 771
    return;
}


#line 1024
[[kernel]] void refineListed(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]], uint device* entryPointParams_survivors_1 [[buffer(5)]])
{

#line 1024
    thread KernelContext_0 kernelContext_5;

#line 1024
    (&kernelContext_5)->entryPointParams_0 = entryPointParams_1;

#line 1024
    (&kernelContext_5)->entryPointParams_data_0 = entryPointParams_data_1;

#line 1024
    (&kernelContext_5)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 1024
    (&kernelContext_5)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 1024
    (&kernelContext_5)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 1024
    (&kernelContext_5)->entryPointParams_survivors_0 = entryPointParams_survivors_1;

#line 1024
    threadgroup array<uint, int(16384)> stg_1;

#line 1024
    (&kernelContext_5)->stg_0 = &stg_1;

#line 1033
    uint pair_1 = entryPointParams_survivors_1[gid_0.x];

#line 1039
    (&kernelContext_5)->_stgBase_0 = 0U;

#line 1039
    filterPair_0(pair_1, lid_0.x, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_5);


    return;
}

