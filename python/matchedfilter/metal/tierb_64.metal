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


#line 116 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_64_fusedTierB.slang"
float2 cload_0(packed_float2 device* b_0, uint i_0)
{

#line 116
    return float2(*(b_0+i_0)) ;
}


#line 152
float2 cmulConj_0(float2 a_0, float2 b_1)
{

#line 152
    float _S2 = a_0.x;

#line 152
    float _S3 = b_1.x;

#line 152
    float _S4 = a_0.y;

#line 152
    float _S5 = b_1.y;

#line 152
    return float2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 154
void r4_0(float2 thread* a_1, float2 thread* b_2, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_1 + *c_0;

#line 156
    float2 t1_0 = *a_1 - *c_0;

#line 156
    float2 t2_0 = *b_2 + *d_0;

#line 156
    float2 t3_0 = *b_2 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_1 = t0_0 + t2_0;

#line 158
    *b_2 = t1_0 + j3_0;

#line 158
    *c_0 = t0_0 - t2_0;

#line 158
    *d_0 = t1_0 - j3_0;
    return;
}


#line 151
float2 cmul_0(float2 a_2, float2 b_3)
{

#line 151
    float _S6 = a_2.x;

#line 151
    float _S7 = b_3.x;

#line 151
    float _S8 = a_2.y;

#line 151
    float _S9 = b_3.y;

#line 151
    return float2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 190
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 197
    uint n1_0 = 0U;
    for(;;)
    {

#line 198
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 198
            break;
        }

#line 198
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 198
        n1_0 = n1_0 + 1U;

#line 198
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 199
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 199
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 200
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 200
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 201
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 201
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 201
    uint k2_0 = 0U;
    for(;;)
    {

#line 202
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 202
            break;
        }

#line 202
        uint _S10 = 4U * k2_0;

#line 202
        r4_0(&(*r_0)[_S10], &(*r_0)[_S10 + 1U], &(*r_0)[_S10 + 2U], &(*r_0)[_S10 + 3U]);

#line 202
        k2_0 = k2_0 + 1U;

#line 202
    }

    float2 t_0 = (*r_0)[int(1)];

#line 204
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 204
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 205
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 205
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 206
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 206
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 207
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 207
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 208
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 208
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 209
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 209
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


#line 140 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_64_fusedTierB.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_data_0;
    packed_float2 device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    uint _stgBase_0;
    uint _tid_0;
    array<uint, int(128)> threadgroup* stg_0;
};


#line 140
void stgPut_0(uint i_1, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 140
    uint _S11 = 2U * i_1;

#line 140
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S11] = (as_type<uint>((v_0.x)));

#line 140
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S11 + 1U] = (as_type<uint>((v_0.y)));

#line 140
    return;
}


#line 141
float2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 141
    uint _S12 = 2U * i_2;

#line 141
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S12]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S12 + 1U]))));
}


#line 231
void exchange_0(array<float2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 231
    uint j_0;

#line 242
    thread array<float2, int(16)> out_0;

#line 242
    uint z_0 = 0U;
    for(;;)
    {

#line 243
        if(z_0 < 16U)
        {
        }
        else
        {

#line 243
            break;
        }

#line 243
        out_0[z_0] = float2(0.0f, 0.0f);

#line 243
        z_0 = z_0 + 1U;

#line 243
    }
    uint _S13 = (1U << lgSpan_0) - 1U;
    uint _S14 = (1U << lgLen_0) - 1U;

#line 245
    uint c_1 = 0U;
    for(;;)
    {

#line 246
        if(c_1 < 1U)
        {
        }
        else
        {

#line 246
            break;
        }

#line 247
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 247
        j_0 = 0U;
        for(;;)
        {

#line 248
            if(j_0 < 16U)
            {
            }
            else
            {

#line 248
                break;
            }

#line 248
            stgPut_0(j_0 * 4U + kernelContext_2->_tid_0, (*r_1)[c_1 * 16U + j_0], kernelContext_2);

#line 248
            j_0 = j_0 + 1U;

#line 248
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 249
        uint d_1 = 0U;
        for(;;)
        {

#line 250
            if(d_1 < 16U)
            {
            }
            else
            {

#line 250
                break;
            }
            uint b_4 = ((*want_0)[d_1]) >> lgLen_0;

#line 252
            uint rem_0 = ((*want_0)[d_1]) & _S14;
            uint i_3 = rem_0 >> lgSpan_0;

#line 253
            uint ln_0 = rem_0 & _S13;
            uint _S15 = c_1 * 16U;

#line 254
            bool _S16;

#line 254
            if(i_3 >= _S15)
            {

#line 254
                _S16 = i_3 < ((c_1 + 1U) * 16U);

#line 254
            }
            else
            {

#line 254
                _S16 = false;

#line 254
            }

#line 254
            if(_S16)
            {

#line 254
                float2 _S17 = stgGet_0((i_3 - _S15) * 4U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S17;

#line 254
            }

#line 250
            d_1 = d_1 + 1U;

#line 250
        }

#line 246
        c_1 = c_1 + 1U;

#line 246
    }

#line 246
    j_0 = 0U;

#line 258
    for(;;)
    {

#line 258
        if(j_0 < 16U)
        {
        }
        else
        {

#line 258
            break;
        }

#line 258
        (*r_1)[j_0] = out_0[j_0];

#line 258
        j_0 = j_0 + 1U;

#line 258
    }
    return;
}


#line 169
void dft4_0(array<float2, int(16)> thread* r_2, uint o_0)
{
    r4_0(&(*r_2)[o_0], &(*r_2)[o_0 + 1U], &(*r_2)[o_0 + 2U], &(*r_2)[o_0 + 3U]);
    float2 t_6 = (*r_2)[o_0 + 1U];

#line 172
    (*r_2)[o_0 + 1U] = (*r_2)[o_0 + 2U];

#line 172
    (*r_2)[o_0 + 2U] = t_6;
    return;
}


#line 215
void innermost_0(array<float2, int(16)> thread* r_3)
{

#line 215
    uint b_5 = 0U;



    for(;;)
    {

#line 219
        if(b_5 < 4U)
        {
        }
        else
        {

#line 219
            break;
        }

#line 219
        dft4_0(r_3, b_5 * 4U);

#line 219
        b_5 = b_5 + 1U;

#line 219
    }

    return;
}


#line 280
uint lgOf_0(uint i_4)
{

#line 280
    uint _S18;

#line 280
    if(i_4 < 1U)
    {

#line 280
        _S18 = 4U;

#line 280
    }
    else
    {

#line 280
        _S18 = 1U;

#line 280
    }

#line 280
    return _S18;
}


#line 282
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(2U);

    uint x_0 = slot_0 >> lg_0;

#line 286
    uint lg_1 = lgOf_0(1U);

#line 286
    uint lg_2 = lgOf_0(0U);

#line 291
    return (((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | ((x_0 >> lg_1) & ((1U << lg_2) - 1U));
}


#line 301
void filterOne_0(uint pair_0, uint d_2, uint t_7, uint tid_0, const array<float2, int(16)> thread* dreg_0, packed_float2 device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{


    uint z_1;

#line 305
    bool live_0;

    thread array<float2, int(16)> r_4;

#line 307
    uint n2_0 = 0U;


    for(;;)
    {

#line 310
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 310
            break;
        }

#line 311
        r_4[n2_0] = cmulConj_0((*dreg_0)[n2_0], cload_0(tmpl_0, t_7 * 64U + tid_0 + 4U * n2_0));

#line 310
        n2_0 = n2_0 + 1U;

#line 310
    }

#line 310
    for(;;)
    {

#line 310
        for(;;)
        {

            for(;;)
            {

#line 314
                thread array<uint, int(16)> want_1;

#line 314
                z_1 = 0U;
                for(;;)
                {

#line 315
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 315
                        break;
                    }

#line 315
                    want_1[z_1] = 0U;

#line 315
                    z_1 = z_1 + 1U;

#line 315
                }



                uint lgTB_0 = firstbithigh_0(4U);
                uint lgLn_0 = firstbithigh_0(64U);
                uint _S19 = tid_0 >> lgTB_0;
                uint _S20 = tid_0 & 3U;

                dft16_0(&r_4);

#line 324
                uint k2_1 = 0U;
                for(;;)
                {

#line 325
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 325
                        break;
                    }

#line 326
                    float ang_0 = 6.28318548202514648f * float(_S20 * k2_1) / 64.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cos(ang_0), sin(ang_0)));

#line 325
                    k2_1 = k2_1 + 1U;

#line 325
                }

#line 332
                uint _S21 = max(4U, 1U);

#line 332
                uint _S22 = 16U / _S21;
                uint _S23 = max(0U, 1U);
                uint _S24 = tid_0 / _S23;

#line 334
                uint _S25 = tid_0 % _S23;

#line 334
                uint d_3 = 0U;
                for(;;)
                {

#line 335
                    if(d_3 < 16U)
                    {
                    }
                    else
                    {

#line 335
                        break;
                    }

#line 336
                    uint j_1 = d_3 / _S21;

#line 336
                    uint m_0 = d_3 % _S21;
                    want_1[d_3] = _S19 * 64U + (_S20 * _S22 + j_1) * 4U + m_0;

#line 335
                    d_3 = d_3 + 1U;

#line 335
                }

#line 335
                thread array<uint, int(16)> _S26 = want_1;

#line 335
                exchange_0(&r_4, &_S26, lgLn_0, lgTB_0, kernelContext_3);

#line 313
                break;
            }

#line 313
            break;
        }

#line 313
        break;
    }

#line 343
    innermost_0(&r_4);

#line 356
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 356
    uint b_6 = tid_0;

#line 364
    for(;;)
    {

#line 364
        if(b_6 < nbins_1)
        {
        }
        else
        {

#line 364
            break;
        }

#line 364
        (*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_6] = thrBits_1;

#line 364
        b_6 = b_6 + 4U;

#line 364
    }

    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;
    thread array<uint, int(16)> myBin_0;

#line 369
    uint i_5 = 0U;
    for(;;)
    {

#line 370
        if(i_5 < 16U)
        {
        }
        else
        {

#line 370
            break;
        }

#line 371
        uint idx_0 = slotToIndex_0(tid_0 * 16U + i_5);
        if(idx_0 >= winStart_1)
        {

#line 372
            live_0 = idx_0 < winEnd_1;

#line 372
        }
        else
        {

#line 372
            live_0 = false;

#line 372
        }



        float _rx_0 = r_4[i_5].x;

#line 376
        float _ry_0 = r_4[i_5].y;
        if(live_0)
        {

#line 377
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 377
        }
        else
        {

#line 377
            n2_0 = 0U;

#line 377
        }

#line 377
        myMag_0[i_5] = n2_0;
        uint off_0 = idx_0 - winStart_1;

#line 385
        if(live_0)
        {

#line 385
            if(binShift_1 >= int(0))
            {

#line 385
                z_1 = off_0 >> uint(binShift_1);

#line 385
            }
            else
            {

#line 385
                uint _S27 = off_0 / binsize_1;

#line 385
                z_1 = _S27;

#line 385
            }

#line 385
        }
        else
        {

#line 385
            z_1 = 0U;

#line 385
        }

#line 385
        myBin_0[i_5] = z_1;

#line 385
        bool _S28;



        if(nbins_1 > 1U)
        {

#line 389
            _S28 = (myMag_0[i_5]) > thrBits_1;

#line 389
        }
        else
        {

#line 389
            _S28 = false;

#line 389
        }

#line 389
        if(_S28)
        {

#line 390
            uint _S29 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_5]])), myMag_0[i_5], memory_order_relaxed);

#line 389
        }

#line 370
        i_5 = i_5 + 1U;

#line 370
    }

#line 402
    if(nbins_1 == 1U)
    {

#line 402
        i_5 = 0U;

#line 402
        uint bestBits_0 = thrBits_1;


        for(;;)
        {

#line 405
            if(i_5 < 16U)
            {
            }
            else
            {

#line 405
                break;
            }

#line 405
            uint _S30 = max(bestBits_0, myMag_0[i_5]);

#line 405
            i_5 = i_5 + 1U;

#line 405
            bestBits_0 = _S30;

#line 405
        }

        uint wm_0 = simd_max(bestBits_0);
        bool _S31 = simd_is_first();

#line 408
        if(_S31)
        {

#line 408
            live_0 = wm_0 > thrBits_1;

#line 408
        }
        else
        {

#line 408
            live_0 = false;

#line 408
        }

#line 408
        if(live_0)
        {

#line 408
            uint _S32 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0])), wm_0, memory_order_relaxed);

#line 408
        }

#line 402
    }

#line 423
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 423
    i_5 = 0U;

#line 428
    for(;;)
    {

#line 428
        if(i_5 < 16U)
        {
        }
        else
        {

#line 428
            break;
        }



        if((myMag_0[i_5]) > thrBits_1)
        {

#line 433
            live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_5]]) == myMag_0[i_5];

#line 433
        }
        else
        {

#line 433
            live_0 = false;

#line 433
        }

#line 433
        if(live_0)
        {

#line 434
            uint o_1 = pair_0 * nbins_1 + myBin_0[i_5];

            *(peakIdx_0+o_1) = int(slotToIndex_0(tid_0 * 16U + i_5));

#line 436
            *(peakVal_0+o_1) = packed_float2(float2(r_4[i_5].x, r_4[i_5].y)) ;

#line 433
        }

#line 428
        i_5 = i_5 + 1U;

#line 428
    }

#line 428
    b_6 = tid_0;

#line 447
    for(;;)
    {

#line 447
        if(b_6 < nbins_1)
        {
        }
        else
        {

#line 447
            break;
        }

#line 448
        if(((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_6]) == thrBits_1)
        {

#line 449
            uint o_2 = pair_0 * nbins_1 + b_6;

            *(peakIdx_0+o_2) = int(-1);

#line 451
            *(peakVal_0+o_2) = packed_float2(float2(0.0f, 0.0f)) ;

#line 448
        }

#line 447
        b_6 = b_6 + 4U;

#line 447
    }

#line 455
    return;
}


void filterPair_0(uint pair_1, uint tid_1, packed_float2 device* data_0, packed_float2 device* tmpl_1, int device* peakIdx_1, packed_float2 device* peakVal_1, uint ntmpl_1, uint winStart_2, uint winEnd_2, uint binsize_2, int binShift_2, uint nbins_2, uint thrBits_2, KernelContext_0 thread* kernelContext_4)
{

#line 465
    kernelContext_4->_tid_0 = tid_1;

#line 475
    uint _S33 = pair_1 / ntmpl_1;

#line 475
    uint _S34 = pair_1 % ntmpl_1;
    thread array<float2, int(16)> dreg_1;

#line 476
    uint n2_1 = 0U;
    for(;;)
    {

#line 477
        if(n2_1 < 16U)
        {
        }
        else
        {

#line 477
            break;
        }

#line 478
        dreg_1[n2_1] = cload_0(data_0, _S33 * 64U + tid_1 + 4U * n2_1);

#line 477
        n2_1 = n2_1 + 1U;

#line 477
    }

#line 477
    uint k_0 = 0U;

    for(;;)
    {

#line 479
        if(k_0 < 1U)
        {
        }
        else
        {

#line 479
            break;
        }

#line 480
        uint _S35 = pair_1 + k_0;

#line 480
        uint _S36 = _S34 + k_0;

#line 480
        thread array<float2, int(16)> _S37 = dreg_1;

#line 480
        filterOne_0(_S35, _S33, _S36, tid_1, &_S37, tmpl_1, peakIdx_1, peakVal_1, winStart_2, winEnd_2, binsize_2, binShift_2, nbins_2, thrBits_2, kernelContext_4);

#line 479
        k_0 = k_0 + 1U;

#line 479
    }


    return;
}

[[kernel]] void fusedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]])
{

#line 485
    thread KernelContext_0 kernelContext_5;

#line 485
    (&kernelContext_5)->entryPointParams_0 = entryPointParams_1;

#line 485
    (&kernelContext_5)->entryPointParams_data_0 = entryPointParams_data_1;

#line 485
    (&kernelContext_5)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 485
    (&kernelContext_5)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 485
    (&kernelContext_5)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 485
    threadgroup array<uint, int(128)> stg_1;

#line 485
    (&kernelContext_5)->stg_0 = &stg_1;

#line 502
    uint _pr_0 = gid_0.x;

#line 502
    uint _t_0 = lid_0.x;
    (&kernelContext_5)->_stgBase_0 = 0U;

#line 503
    filterPair_0(_pr_0, _t_0, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_5);

#line 511
    return;
}

