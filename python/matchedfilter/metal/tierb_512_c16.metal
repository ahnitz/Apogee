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


#line 112 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_512_fusedTierB_c16.slang"
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


#line 154
void r4_0(half2 thread* a_1, half2 thread* b_2, half2 thread* c_0, half2 thread* d_0)
{
    half2 t0_0 = *a_1 + *c_0;

#line 156
    half2 t1_0 = *a_1 - *c_0;

#line 156
    half2 t2_0 = *b_2 + *d_0;

#line 156
    half2 t3_0 = *b_2 - *d_0;
    half2 j3_0 = half2(- t3_0.y, t3_0.x);
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


#line 190
void dft16_0(array<half2, int(16)> thread* r_0)
{
    half2 W1_0 = half2(0.923828125h, 0.382568359375h);
    half2 W2_0 = half2(0.70703125h, 0.70703125h);
    half2 W3_0 = half2(0.382568359375h, 0.923828125h);
    half2 W4_0 = half2(0.0h, 1.0h);
    half2 W6_0 = half2(-0.70703125h, 0.70703125h);
    half2 W9_0 = half2(-0.923828125h, -0.382568359375h);

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

    half2 t_0 = (*r_0)[int(1)];

#line 204
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 204
    (*r_0)[int(4)] = t_0;
    half2 t_1 = (*r_0)[int(2)];

#line 205
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 205
    (*r_0)[int(8)] = t_1;
    half2 t_2 = (*r_0)[int(3)];

#line 206
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 206
    (*r_0)[int(12)] = t_2;
    half2 t_3 = (*r_0)[int(6)];

#line 207
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 207
    (*r_0)[int(9)] = t_3;
    half2 t_4 = (*r_0)[int(7)];

#line 208
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 208
    (*r_0)[int(13)] = t_4;
    half2 t_5 = (*r_0)[int(11)];

#line 209
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 209
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


#line 133 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_512_fusedTierB_c16.slang"
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


#line 231
void exchange_0(array<half2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 231
    uint j_0;

#line 242
    thread array<half2, int(16)> out_0;

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
        out_0[z_0] = half2(0.0h, 0.0h);

#line 243
        z_0 = z_0 + 1U;

#line 243
    }
    uint _S11 = (1U << lgSpan_0) - 1U;
    uint _S12 = (1U << lgLen_0) - 1U;

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
            stgPut_0(j_0 * 32U + kernelContext_2->_tid_0, (*r_1)[c_1 * 16U + j_0], kernelContext_2);

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
            uint rem_0 = ((*want_0)[d_1]) & _S12;
            uint i_3 = rem_0 >> lgSpan_0;

#line 253
            uint ln_0 = rem_0 & _S11;
            uint _S13 = c_1 * 16U;

#line 254
            bool _S14;

#line 254
            if(i_3 >= _S13)
            {

#line 254
                _S14 = i_3 < ((c_1 + 1U) * 16U);

#line 254
            }
            else
            {

#line 254
                _S14 = false;

#line 254
            }

#line 254
            if(_S14)
            {

#line 254
                half2 _S15 = stgGet_0((i_3 - _S13) * 32U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S15;

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


#line 165
void dft2_0(array<half2, int(16)> thread* r_2, uint o_0)
{
    half2 a_3 = (*r_2)[o_0];

#line 167
    half2 b_5 = (*r_2)[o_0 + 1U];

#line 167
    (*r_2)[o_0] = (*r_2)[o_0] + (*r_2)[o_0 + 1U];

#line 167
    (*r_2)[o_0 + 1U] = a_3 - b_5;
    return;
}


#line 215
void innermost_0(array<half2, int(16)> thread* r_3)
{

#line 215
    uint b_6 = 0U;

#line 220
    for(;;)
    {

#line 220
        if(b_6 < 8U)
        {
        }
        else
        {

#line 220
            break;
        }

#line 220
        dft2_0(r_3, b_6 * 2U);

#line 220
        b_6 = b_6 + 1U;

#line 220
    }
    return;
}


#line 280
uint lgOf_0(uint i_4)
{

#line 280
    uint _S16;

#line 280
    if(i_4 < 2U)
    {

#line 280
        _S16 = 4U;

#line 280
    }
    else
    {

#line 280
        _S16 = 1U;

#line 280
    }

#line 280
    return _S16;
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


#line 311
void filterOne_0(uint pair_0, uint d_2, uint t_6, uint tid_0, const array<half2, int(16)> thread* dreg_0, uint device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{



    uint z_1;

#line 316
    uint _S17;

#line 316
    uint k2_1;

#line 316
    uint _S18;

#line 316
    uint d_3;

#line 316
    bool live_0;

    thread array<half2, int(16)> r_4;

#line 318
    uint n2_0 = 0U;


    for(;;)
    {

#line 321
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 321
            break;
        }

#line 322
        r_4[n2_0] = cmulConj_0((*dreg_0)[n2_0], cload_0(tmpl_0, t_6 * 512U + tid_0 + 32U * n2_0));

#line 321
        n2_0 = n2_0 + 1U;

#line 321
    }

#line 321
    for(;;)
    {

#line 321
        for(;;)
        {

            for(;;)
            {

#line 325
                thread array<uint, int(16)> want_1;

#line 325
                z_1 = 0U;
                for(;;)
                {

#line 326
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 326
                        break;
                    }

#line 326
                    want_1[z_1] = 0U;

#line 326
                    z_1 = z_1 + 1U;

#line 326
                }



                uint lgTB_0 = firstbithigh_0(32U);

#line 330
                _S17 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(512U);

                uint _S19 = tid_0 & 31U;

                dft16_0(&r_4);

#line 335
                k2_1 = 0U;
                for(;;)
                {

#line 336
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 336
                        break;
                    }

#line 337
                    float ang_0 = 6.28318548202514648f * float(_S19 * k2_1) / 512.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], half2(half(cos(ang_0)), half(sin(ang_0))));

#line 336
                    k2_1 = k2_1 + 1U;

#line 336
                }

#line 343
                uint _S20 = max(32U, 1U);

#line 343
                uint _S21 = 16U / _S20;
                uint _S22 = max(2U, 1U);

#line 344
                _S18 = _S22;
                uint _S23 = tid_0 / _S22;

#line 345
                uint _S24 = tid_0 % _S22;

#line 345
                d_3 = 0U;
                for(;;)
                {

#line 346
                    if(d_3 < 16U)
                    {
                    }
                    else
                    {

#line 346
                        break;
                    }

#line 347
                    uint j_1 = d_3 / _S20;

#line 347
                    uint m_0 = d_3 % _S20;
                    want_1[d_3] = _S23 * 32U + _S24 + _S22 * d_3;

#line 346
                    d_3 = d_3 + 1U;

#line 346
                }

#line 346
                thread array<uint, int(16)> _S25 = want_1;

#line 346
                exchange_0(&r_4, &_S25, lgLn_0, lgTB_0, kernelContext_3);

#line 324
                break;
            }

#line 324
            break;
        }

#line 324
        for(;;)
        {

#line 324
            for(;;)
            {

#line 325
                thread array<uint, int(16)> want_2;

#line 325
                z_1 = 0U;
                for(;;)
                {

#line 326
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 326
                        break;
                    }

#line 326
                    want_2[z_1] = 0U;

#line 326
                    z_1 = z_1 + 1U;

#line 326
                }



                uint lgTB_1 = firstbithigh_0(2U);

                uint _S26 = tid_0 >> lgTB_1;
                uint _S27 = tid_0 & 1U;

                dft16_0(&r_4);

#line 335
                k2_1 = 0U;
                for(;;)
                {

#line 336
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 336
                        break;
                    }

#line 337
                    float ang_1 = 6.28318548202514648f * float(_S27 * k2_1) / 32.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], half2(half(cos(ang_1)), half(sin(ang_1))));

#line 336
                    k2_1 = k2_1 + 1U;

#line 336
                }

#line 343
                uint _S28 = 16U / _S18;
                uint _S29 = max(0U, 1U);
                uint _S30 = tid_0 / _S29;

#line 345
                uint _S31 = tid_0 % _S29;

#line 345
                d_3 = 0U;
                for(;;)
                {

#line 346
                    if(d_3 < 16U)
                    {
                    }
                    else
                    {

#line 346
                        break;
                    }

#line 347
                    uint j_2 = d_3 / _S18;

#line 347
                    uint m_1 = d_3 % _S18;
                    want_2[d_3] = _S26 * 32U + (_S27 * _S28 + j_2) * 2U + m_1;

#line 346
                    d_3 = d_3 + 1U;

#line 346
                }

#line 346
                thread array<uint, int(16)> _S32 = want_2;

#line 346
                exchange_0(&r_4, &_S32, _S17, lgTB_1, kernelContext_3);

#line 324
                break;
            }

#line 324
            break;
        }

#line 324
        break;
    }

#line 354
    innermost_0(&r_4);

#line 367
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 367
    uint b_7 = tid_0;
    for(;;)
    {

#line 368
        if(b_7 < nbins_1)
        {
        }
        else
        {

#line 368
            break;
        }

#line 368
        (*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_7] = thrBits_1;

#line 368
        b_7 = b_7 + 32U;

#line 368
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;
    thread array<uint, int(16)> myBin_0;

#line 372
    uint i_5 = 0U;
    for(;;)
    {

#line 373
        if(i_5 < 16U)
        {
        }
        else
        {

#line 373
            break;
        }

#line 374
        uint idx_0 = slotToIndex_0(tid_0 * 16U + i_5);
        if(idx_0 >= winStart_1)
        {

#line 375
            live_0 = idx_0 < winEnd_1;

#line 375
        }
        else
        {

#line 375
            live_0 = false;

#line 375
        }



        float _rx_0 = float(r_4[i_5].x);

#line 379
        float _ry_0 = float(r_4[i_5].y);
        if(live_0)
        {

#line 380
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 380
        }
        else
        {

#line 380
            n2_0 = 0U;

#line 380
        }

#line 380
        myMag_0[i_5] = n2_0;
        uint off_0 = idx_0 - winStart_1;



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
                uint _S33 = off_0 / binsize_1;

#line 385
                z_1 = _S33;

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
        bool _S34;

        if(nbins_1 > 1U)
        {

#line 387
            _S34 = (myMag_0[i_5]) > thrBits_1;

#line 387
        }
        else
        {

#line 387
            _S34 = false;

#line 387
        }

#line 387
        if(_S34)
        {

#line 388
            uint _S35 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_5]])), myMag_0[i_5], memory_order_relaxed);

#line 387
        }

#line 373
        i_5 = i_5 + 1U;

#line 373
    }

#line 396
    if(nbins_1 == 1U)
    {

#line 396
        i_5 = 0U;

#line 396
        uint bestBits_0 = thrBits_1;

        for(;;)
        {

#line 398
            if(i_5 < 16U)
            {
            }
            else
            {

#line 398
                break;
            }

#line 398
            uint _S36 = max(bestBits_0, myMag_0[i_5]);

#line 398
            i_5 = i_5 + 1U;

#line 398
            bestBits_0 = _S36;

#line 398
        }
        uint wm_0 = simd_max(bestBits_0);
        bool _S37 = simd_is_first();

#line 400
        if(_S37)
        {

#line 400
            live_0 = wm_0 > thrBits_1;

#line 400
        }
        else
        {

#line 400
            live_0 = false;

#line 400
        }

#line 400
        if(live_0)
        {

#line 400
            uint _S38 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0])), wm_0, memory_order_relaxed);

#line 400
        }

#line 396
    }

#line 402
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 402
    i_5 = 0U;

#line 407
    for(;;)
    {

#line 407
        if(i_5 < 16U)
        {
        }
        else
        {

#line 407
            break;
        }

#line 408
        if((myMag_0[i_5]) > thrBits_1)
        {

#line 408
            live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_5]]) == myMag_0[i_5];

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

#line 409
            uint o_1 = pair_0 * nbins_1 + myBin_0[i_5];
            *(peakIdx_0+o_1) = int(slotToIndex_0(tid_0 * 16U + i_5));

#line 410
            *(peakVal_0+o_1) = packed_float2(float2(float(r_4[i_5].x), float(r_4[i_5].y))) ;

#line 408
        }

#line 407
        i_5 = i_5 + 1U;

#line 407
    }

#line 407
    b_7 = tid_0;

#line 416
    for(;;)
    {

#line 416
        if(b_7 < nbins_1)
        {
        }
        else
        {

#line 416
            break;
        }

#line 417
        if(((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_7]) == thrBits_1)
        {

#line 418
            uint o_2 = pair_0 * nbins_1 + b_7;
            *(peakIdx_0+o_2) = int(-1);

#line 419
            *(peakVal_0+o_2) = packed_float2(float2(0.0f, 0.0f)) ;

#line 417
        }

#line 416
        b_7 = b_7 + 32U;

#line 416
    }

#line 423
    return;
}


void filterPair_0(uint pair_1, uint tid_1, uint device* data_0, uint device* tmpl_1, int device* peakIdx_1, packed_float2 device* peakVal_1, uint ntmpl_1, uint winStart_2, uint winEnd_2, uint binsize_2, int binShift_2, uint nbins_2, uint thrBits_2, KernelContext_0 thread* kernelContext_4)
{

#line 434
    kernelContext_4->_tid_0 = tid_1;
    uint _S39 = pair_1 / ntmpl_1;

#line 435
    uint _S40 = pair_1 % ntmpl_1;
    thread array<half2, int(16)> dreg_1;

#line 436
    uint n2_1 = 0U;
    for(;;)
    {

#line 437
        if(n2_1 < 16U)
        {
        }
        else
        {

#line 437
            break;
        }

#line 438
        dreg_1[n2_1] = cload_0(data_0, _S39 * 512U + tid_1 + 32U * n2_1);

#line 437
        n2_1 = n2_1 + 1U;

#line 437
    }

#line 437
    uint k_0 = 0U;

    for(;;)
    {

#line 439
        if(k_0 < 1U)
        {
        }
        else
        {

#line 439
            break;
        }

#line 440
        uint _S41 = pair_1 + k_0;

#line 440
        uint _S42 = _S40 + k_0;

#line 440
        thread array<half2, int(16)> _S43 = dreg_1;

#line 440
        filterOne_0(_S41, _S39, _S42, tid_1, &_S43, tmpl_1, peakIdx_1, peakVal_1, winStart_2, winEnd_2, binsize_2, binShift_2, nbins_2, thrBits_2, kernelContext_4);

#line 439
        k_0 = k_0 + 1U;

#line 439
    }


    return;
}

[[kernel]] void fusedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], uint device* entryPointParams_data_1 [[buffer(1)]], uint device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]])
{

#line 445
    thread KernelContext_0 kernelContext_5;

#line 445
    (&kernelContext_5)->entryPointParams_0 = entryPointParams_1;

#line 445
    (&kernelContext_5)->entryPointParams_data_0 = entryPointParams_data_1;

#line 445
    (&kernelContext_5)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 445
    (&kernelContext_5)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 445
    (&kernelContext_5)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 445
    threadgroup array<uint, int(512)> stg_1;

#line 445
    (&kernelContext_5)->stg_0 = &stg_1;

#line 462
    uint _pr_0 = gid_0.x;

#line 462
    uint _t_0 = lid_0.x;
    (&kernelContext_5)->_stgBase_0 = 0U;

#line 463
    filterPair_0(_pr_0, _t_0, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_5);

#line 471
    return;
}

