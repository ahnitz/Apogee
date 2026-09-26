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


#line 149 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_16384_fusedTierB_lds32.slang"
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


#line 338
void r4_0(float2 thread* a_1, float2 thread* b_2, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_1 + *c_0;

#line 340
    float2 t1_0 = *a_1 - *c_0;

#line 340
    float2 t2_0 = *b_2 + *d_0;

#line 340
    float2 t3_0 = *b_2 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
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
float2 cmul_0(float2 a_2, float2 b_3)
{

#line 188
    float _S6 = a_2.x;

#line 188
    float _S7 = b_3.x;

#line 188
    float _S8 = a_2.y;

#line 188
    float _S9 = b_3.y;

#line 188
    return float2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
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


#line 177 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_16384_fusedTierB_lds32.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_data_0;
    packed_float2 device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    uint _stgBase_0;
    uint _tid_0;
    array<uint, int(8192)> threadgroup* stg_0;
};


#line 177
void stgPut_0(uint i_1, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 177
    uint _S11 = 2U * i_1;

#line 177
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S11] = (as_type<uint>((v_0.x)));

#line 177
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S11 + 1U] = (as_type<uint>((v_0.y)));

#line 177
    return;
}


#line 178
float2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 178
    uint _S12 = 2U * i_2;

#line 178
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S12]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S12 + 1U]))));
}


#line 499
void exchange_0(array<float2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 499
    uint j_0;

#line 510
    thread array<float2, int(16)> out_0;

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
        out_0[z_0] = float2(0.0f, 0.0f);

#line 511
        z_0 = z_0 + 1U;

#line 511
    }
    uint _S13 = (1U << lgSpan_0) - 1U;
    uint _S14 = (1U << lgLen_0) - 1U;

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
        j_0 = 0U;
        for(;;)
        {

#line 516
            if(j_0 < 4U)
            {
            }
            else
            {

#line 516
                break;
            }

#line 516
            stgPut_0(j_0 * 1024U + kernelContext_2->_tid_0, (*r_1)[c_1 * 4U + j_0], kernelContext_2);

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
            uint rem_0 = ((*want_0)[d_1]) & _S14;
            uint i_3 = rem_0 >> lgSpan_0;

#line 521
            uint ln_0 = rem_0 & _S13;
            uint _S15 = c_1 * 4U;

#line 522
            bool _S16;

#line 522
            if(i_3 >= _S15)
            {

#line 522
                _S16 = i_3 < ((c_1 + 1U) * 4U);

#line 522
            }
            else
            {

#line 522
                _S16 = false;

#line 522
            }

#line 522
            if(_S16)
            {

#line 522
                float2 _S17 = stgGet_0((i_3 - _S15) * 1024U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S17;

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


#line 353
void dft4_0(array<float2, int(16)> thread* r_2, uint o_0)
{
    r4_0(&(*r_2)[o_0], &(*r_2)[o_0 + 1U], &(*r_2)[o_0 + 2U], &(*r_2)[o_0 + 3U]);
    float2 t_6 = (*r_2)[o_0 + 1U];

#line 356
    (*r_2)[o_0 + 1U] = (*r_2)[o_0 + 2U];

#line 356
    (*r_2)[o_0 + 2U] = t_6;
    return;
}


#line 477
void innermost_0(array<float2, int(16)> thread* r_3)
{

#line 477
    uint b_5 = 0U;

#line 486
    for(;;)
    {

#line 486
        if(b_5 < 4U)
        {
        }
        else
        {

#line 486
            break;
        }

#line 486
        dft4_0(r_3, b_5 * 4U);

#line 486
        b_5 = b_5 + 1U;

#line 486
    }


    return;
}


#line 581
void transform_0(array<float2, int(16)> thread* r_4, uint tid_0, KernelContext_0 thread* kernelContext_3)
{

#line 581
    uint z_1;

#line 581
    uint _S18;

#line 581
    uint k2_1;

#line 581
    float cr_0;

#line 581
    float ci_0;

#line 581
    uint _S19;

#line 581
    uint d_2;

#line 581
    uint _S20;

#line 581
    uint _S21;

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



                uint lgTB_0 = firstbithigh_0(1024U);

#line 13
                _S18 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(16384U);

                uint lane_0 = tid_0 & 1023U;


                dft16_0(r_4);

#line 27
                float a1_0 = 6.28318548202514648f * float(lane_0) / 16384.0f;
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
                uint _S25 = max(1024U, 1U);

#line 40
                uint _S26 = 16U / _S25;
                uint _S27 = max(64U, 1U);

#line 41
                _S19 = _S27;
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
                    uint j_1 = d_2 / _S25;

#line 44
                    uint m_0 = d_2 % _S25;
                    want_1[d_2] = _S28 * 1024U + _S29 + _S27 * d_2;

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



                uint lgTB_1 = firstbithigh_0(64U);

#line 13
                _S20 = lgTB_1;


                uint lane_1 = tid_0 & 63U;


                dft16_0(r_4);

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
                uint _S34 = 16U / _S19;
                uint _S35 = max(4U, 1U);

#line 41
                _S21 = _S35;
                uint _S36 = tid_0 / _S35;

#line 42
                uint _S37 = tid_0 % _S35;

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
                    uint j_2 = d_2 / _S19;

#line 44
                    uint m_1 = d_2 % _S19;
                    want_2[d_2] = _S36 * 64U + _S37 + _S35 * d_2;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(16)> _S38 = want_2;

#line 43
                exchange_0(r_4, &_S38, _S18, lgTB_1, kernelContext_3);

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



                uint lgTB_2 = firstbithigh_0(4U);

                uint _S39 = tid_0 >> lgTB_2;
                uint lane_2 = tid_0 & 3U;


                dft16_0(r_4);

#line 27
                float a1_2 = 6.28318548202514648f * float(lane_2) / 64.0f;
                float _S40 = cos(a1_2);

#line 28
                float _S41 = sin(a1_2);

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
                    float nr_2 = cr_0 * _S40 - ci_0 * _S41;
                    float _S42 = cr_0 * _S41 + ci_0 * _S40;

#line 30
                    k2_1 = k2_1 + 1U;

#line 30
                    cr_0 = nr_2;

#line 30
                    ci_0 = _S42;

#line 30
                }

#line 40
                uint _S43 = 16U / _S21;
                uint _S44 = max(0U, 1U);
                uint _S45 = tid_0 / _S44;

#line 42
                uint _S46 = tid_0 % _S44;

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
                    uint m_2 = d_2 % _S21;
                    want_3[d_2] = _S39 * 64U + (lane_2 * _S43 + j_3) * 4U + m_2;

#line 43
                    d_2 = d_2 + 1U;

#line 43
                }

#line 43
                thread array<uint, int(16)> _S47 = want_3;

#line 43
                exchange_0(r_4, &_S47, _S20, lgTB_2, kernelContext_3);

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

#line 584 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_16384_fusedTierB_lds32.slang"
    return;
}


#line 550
uint lgOf_0(uint i_4)
{

#line 550
    uint _S48;

#line 550
    if(i_4 < 3U)
    {

#line 550
        _S48 = 4U;

#line 550
    }
    else
    {

#line 550
        _S48 = 1U;

#line 550
    }

#line 550
    return _S48;
}


#line 552
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(4U);

    uint x_0 = slot_0 >> lg_0;

#line 556
    uint lg_1 = lgOf_0(3U);

    uint x_1 = x_0 >> lg_1;

#line 556
    uint lg_2 = lgOf_0(2U);

    uint x_2 = x_1 >> lg_2;

#line 556
    uint lg_3 = lgOf_0(1U);

#line 556
    uint lg_4 = lgOf_0(0U);

#line 561
    return (((((((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | (x_1 & ((1U << lg_2) - 1U))) << lg_3) | (x_2 & ((1U << lg_3) - 1U))) << lg_4) | ((x_2 >> lg_3) & ((1U << lg_4) - 1U));
}


#line 596
void filterPair_0(uint pair_0, uint tid_1, packed_float2 device* data_0, packed_float2 device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint ntmpl_1, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_4)
{

#line 610
    kernelContext_4->_tid_0 = tid_1;
    uint _S49 = pair_0 / ntmpl_1;

#line 611
    uint _S50 = pair_0 % ntmpl_1;

    thread array<float2, int(16)> r_5;

#line 613
    uint n2_0 = 0U;

#line 624
    for(;;)
    {

#line 624
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 624
            break;
        }

#line 625
        uint idx_0 = tid_1 + 1024U * n2_0;
        r_5[n2_0] = cmulConj_0(cload_0(data_0, _S49 * 16384U + idx_0), cload_0(tmpl_0, _S50 * 16384U + idx_0));

#line 624
        n2_0 = n2_0 + 1U;

#line 624
    }

#line 624
    transform_0(&r_5, tid_1, kernelContext_4);

#line 643
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 643
    uint b_6 = tid_1;

#line 651
    for(;;)
    {

#line 651
        if(b_6 < nbins_1)
        {
        }
        else
        {

#line 651
            break;
        }

#line 651
        (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + b_6] = thrBits_1;

#line 651
        b_6 = b_6 + 1024U;

#line 651
    }
    bool _S51 = nbins_1 == 1U;

#line 652
    bool live_0;

#line 652
    if(_S51)
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

    thread array<uint, int(16)> myMag_0;
    thread array<uint, int(16)> myBin_0;

#line 657
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
        uint idx_1 = slotToIndex_0(tid_1 * 16U + i_5);
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



        float _rx_0 = r_5[i_5].x;

#line 664
        float _ry_0 = r_5[i_5].y;
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
                b_6 = off_0 >> uint(binShift_1);

#line 673
            }
            else
            {

#line 673
                uint _S52 = off_0 / binsize_1;

#line 673
                b_6 = _S52;

#line 673
            }

#line 673
        }
        else
        {

#line 673
            b_6 = 0U;

#line 673
        }

#line 673
        myBin_0[i_5] = b_6;

#line 673
        bool _S53;



        if(nbins_1 > 1U)
        {

#line 677
            _S53 = (myMag_0[i_5]) > thrBits_1;

#line 677
        }
        else
        {

#line 677
            _S53 = false;

#line 677
        }

#line 677
        if(_S53)
        {

#line 678
            uint _S54 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_5]])), myMag_0[i_5], memory_order_relaxed);

#line 677
        }

#line 658
        i_5 = i_5 + 1U;

#line 658
    }

#line 658
    uint winner_0;

#line 690
    if(_S51)
    {

#line 690
        winner_0 = thrBits_1;

#line 690
        i_5 = 0U;


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
            uint _S55 = max(winner_0, myMag_0[i_5]);

#line 693
            uint i_6 = i_5 + 1U;

#line 693
            winner_0 = _S55;

#line 693
            i_5 = i_6;

#line 693
        }

        uint wm_0 = simd_max(winner_0);
        bool _S56 = simd_is_first();

#line 696
        if(_S56)
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
            uint _S57 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0])), wm_0, memory_order_relaxed);

#line 696
        }

#line 690
    }

#line 711
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 718
    if(_S51)
    {

#line 718
        winner_0 = 4294967295U;

#line 718
        i_5 = 0U;


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
        bool _S58 = simd_is_first();

#line 726
        if(_S58)
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
            uint _S59 = atomic_fetch_min_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U])), waveWinner_0, memory_order_relaxed);

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
            uint _S60 = tid_1 * 16U + i_5;

#line 733
            if(_S60 == (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + 1U])
            {

#line 734
                *(peakIdx_0+pair_0) = int(slotToIndex_0(_S60));

#line 734
                *(peakVal_0+pair_0) = packed_float2(float2(r_5[i_5].x, r_5[i_5].y)) ;

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
            if(i_5 < 16U)
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
        b_6 = tid_1;
        for(;;)
        {

#line 751
            if(b_6 < nbins_1)
            {
            }
            else
            {

#line 751
                break;
            }

#line 751
            (*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + b_6] = 4294967295U;

#line 751
            b_6 = b_6 + 1024U;

#line 751
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 752
        i_5 = 0U;
        for(;;)
        {

#line 753
            if(i_5 < 16U)
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
                uint _S61 = atomic_fetch_min_explicit(((atomic_uint threadgroup*)(&(*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_5]])), tid_1 * 16U + i_5, memory_order_relaxed);

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
            if(i_5 < 16U)
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
                live_0 = ((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + myBin_0[i_5]]) == (tid_1 * 16U + i_5);

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
                uint o_1 = pair_0 * nbins_1 + myBin_0[i_5];
                *(peakIdx_0+o_1) = int(slotToIndex_0(tid_1 * 16U + i_5));

#line 759
                *(peakVal_0+o_1) = packed_float2(float2(r_5[i_5].x, r_5[i_5].y)) ;

#line 757
            }

#line 756
            i_5 = i_5 + 1U;

#line 756
        }

#line 756
        b_6 = tid_1;

#line 763
        for(;;)
        {

#line 763
            if(b_6 < nbins_1)
            {
            }
            else
            {

#line 763
                break;
            }

#line 764
            if(((*kernelContext_4->stg_0)[kernelContext_4->_stgBase_0 + b_6]) == 4294967295U)
            {

#line 765
                uint _S62 = pair_0 * nbins_1 + b_6;

#line 765
                *(peakIdx_0+_S62) = int(-1);

#line 765
                *(peakVal_0+_S62) = packed_float2(float2(0.0f, 0.0f)) ;

#line 764
            }

#line 763
            b_6 = b_6 + 1024U;

#line 763
        }

#line 718
    }

#line 771
    return;
}


#line 948
[[kernel]] void fusedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]])
{

#line 948
    thread KernelContext_0 kernelContext_5;

#line 948
    (&kernelContext_5)->entryPointParams_0 = entryPointParams_1;

#line 948
    (&kernelContext_5)->entryPointParams_data_0 = entryPointParams_data_1;

#line 948
    (&kernelContext_5)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 948
    (&kernelContext_5)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 948
    (&kernelContext_5)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 948
    threadgroup array<uint, int(8192)> stg_1;

#line 948
    (&kernelContext_5)->stg_0 = &stg_1;

#line 965
    uint _pr_0 = gid_0.x;

#line 965
    uint _t_0 = lid_0.x;
    (&kernelContext_5)->_stgBase_0 = 0U;

#line 966
    filterPair_0(_pr_0, _t_0, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_5);

#line 974
    return;
}

