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


#line 97 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_512_gatedTierB.slang"
float2 cload_0(packed_float2 device* b_0, uint i_0)
{

#line 97
    return float2(*(b_0+i_0)) ;
}


#line 111
float2 cmulConj_0(float2 a_0, float2 b_1)
{

#line 111
    float _S2 = a_0.x;

#line 111
    float _S3 = b_1.x;

#line 111
    float _S4 = a_0.y;

#line 111
    float _S5 = b_1.y;

#line 111
    return float2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 113
void r4_0(float2 thread* a_1, float2 thread* b_2, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_1 + *c_0;

#line 115
    float2 t1_0 = *a_1 - *c_0;

#line 115
    float2 t2_0 = *b_2 + *d_0;

#line 115
    float2 t3_0 = *b_2 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_1 = t0_0 + t2_0;

#line 117
    *b_2 = t1_0 + j3_0;

#line 117
    *c_0 = t0_0 - t2_0;

#line 117
    *d_0 = t1_0 - j3_0;
    return;
}


#line 110
float2 cmul_0(float2 a_2, float2 b_3)
{

#line 110
    float _S6 = a_2.x;

#line 110
    float _S7 = b_3.x;

#line 110
    float _S8 = a_2.y;

#line 110
    float _S9 = b_3.y;

#line 110
    return float2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 149
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 156
    uint n1_0 = 0U;
    for(;;)
    {

#line 157
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 157
            break;
        }

#line 157
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 157
        n1_0 = n1_0 + 1U;

#line 157
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 158
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 158
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 159
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 159
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 160
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 160
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 160
    uint k2_0 = 0U;
    for(;;)
    {

#line 161
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 161
            break;
        }

#line 161
        uint _S10 = 4U * k2_0;

#line 161
        r4_0(&(*r_0)[_S10], &(*r_0)[_S10 + 1U], &(*r_0)[_S10 + 2U], &(*r_0)[_S10 + 3U]);

#line 161
        k2_0 = k2_0 + 1U;

#line 161
    }

    float2 t_0 = (*r_0)[int(1)];

#line 163
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 163
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 164
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 164
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 165
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 165
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 166
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 166
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 167
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 167
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 168
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 168
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
    float thr_0;
};


#line 100 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_512_gatedTierB.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_data_0;
    packed_float2 device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    packed_float2 device* entryPointParams_coarse_0;
    uint _tid_0;
    array<uint, int(1024)> threadgroup* stg_0;
};


#line 100
void stgPut_0(uint i_1, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 100
    uint _S11 = 2U * i_1;

#line 100
    (*kernelContext_0->stg_0)[_S11] = (as_type<uint>((v_0.x)));

#line 100
    (*kernelContext_0->stg_0)[_S11 + 1U] = (as_type<uint>((v_0.y)));

#line 100
    return;
}


#line 101
float2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 101
    uint _S12 = 2U * i_2;

#line 101
    return float2((as_type<float>(((*kernelContext_1->stg_0)[_S12]))), (as_type<float>(((*kernelContext_1->stg_0)[_S12 + 1U]))));
}


#line 190
void exchange_0(array<float2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 190
    uint j_0;

#line 201
    thread array<float2, int(16)> out_0;

#line 201
    uint z_0 = 0U;
    for(;;)
    {

#line 202
        if(z_0 < 16U)
        {
        }
        else
        {

#line 202
            break;
        }

#line 202
        out_0[z_0] = float2(0.0f, 0.0f);

#line 202
        z_0 = z_0 + 1U;

#line 202
    }
    uint _S13 = (1U << lgSpan_0) - 1U;
    uint _S14 = (1U << lgLen_0) - 1U;

#line 204
    uint c_1 = 0U;
    for(;;)
    {

#line 205
        if(c_1 < 1U)
        {
        }
        else
        {

#line 205
            break;
        }

#line 206
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 206
        j_0 = 0U;
        for(;;)
        {

#line 207
            if(j_0 < 16U)
            {
            }
            else
            {

#line 207
                break;
            }

#line 207
            stgPut_0(j_0 * 32U + kernelContext_2->_tid_0, (*r_1)[c_1 * 16U + j_0], kernelContext_2);

#line 207
            j_0 = j_0 + 1U;

#line 207
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 208
        uint d_1 = 0U;
        for(;;)
        {

#line 209
            if(d_1 < 16U)
            {
            }
            else
            {

#line 209
                break;
            }
            uint b_4 = ((*want_0)[d_1]) >> lgLen_0;

#line 211
            uint rem_0 = ((*want_0)[d_1]) & _S14;
            uint i_3 = rem_0 >> lgSpan_0;

#line 212
            uint ln_0 = rem_0 & _S13;
            uint _S15 = c_1 * 16U;

#line 213
            bool _S16;

#line 213
            if(i_3 >= _S15)
            {

#line 213
                _S16 = i_3 < ((c_1 + 1U) * 16U);

#line 213
            }
            else
            {

#line 213
                _S16 = false;

#line 213
            }

#line 213
            if(_S16)
            {

#line 213
                float2 _S17 = stgGet_0((i_3 - _S15) * 32U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S17;

#line 213
            }

#line 209
            d_1 = d_1 + 1U;

#line 209
        }

#line 205
        c_1 = c_1 + 1U;

#line 205
    }

#line 205
    j_0 = 0U;

#line 217
    for(;;)
    {

#line 217
        if(j_0 < 16U)
        {
        }
        else
        {

#line 217
            break;
        }

#line 217
        (*r_1)[j_0] = out_0[j_0];

#line 217
        j_0 = j_0 + 1U;

#line 217
    }
    return;
}


#line 124
void dft2_0(array<float2, int(16)> thread* r_2, uint o_0)
{
    float2 a_3 = (*r_2)[o_0];

#line 126
    float2 b_5 = (*r_2)[o_0 + 1U];

#line 126
    (*r_2)[o_0] = (*r_2)[o_0] + (*r_2)[o_0 + 1U];

#line 126
    (*r_2)[o_0 + 1U] = a_3 - b_5;
    return;
}


#line 174
void innermost_0(array<float2, int(16)> thread* r_3)
{

#line 174
    uint b_6 = 0U;

#line 179
    for(;;)
    {

#line 179
        if(b_6 < 8U)
        {
        }
        else
        {

#line 179
            break;
        }

#line 179
        dft2_0(r_3, b_6 * 2U);

#line 179
        b_6 = b_6 + 1U;

#line 179
    }
    return;
}


#line 239
uint lgOf_0(uint i_4)
{

#line 239
    uint _S18;

#line 239
    if(i_4 < 2U)
    {

#line 239
        _S18 = 4U;

#line 239
    }
    else
    {

#line 239
        _S18 = 1U;

#line 239
    }

#line 239
    return _S18;
}


#line 241
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(2U);

    uint x_0 = slot_0 >> lg_0;

#line 245
    uint lg_1 = lgOf_0(1U);

#line 245
    uint lg_2 = lgOf_0(0U);

#line 250
    return (((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | ((x_0 >> lg_1) & ((1U << lg_2) - 1U));
}




void filterPair_0(uint pair_0, uint tid_0, packed_float2 device* data_0, packed_float2 device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint ntmpl_1, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{



    uint z_1;

#line 261
    uint _S19;

#line 261
    uint k2_1;

#line 261
    uint _S20;

#line 261
    uint d_2;

#line 261
    bool live_0;

    kernelContext_3->_tid_0 = tid_0;
    uint _S21 = pair_0 / ntmpl_1;

#line 264
    uint _S22 = pair_0 % ntmpl_1;
    thread array<float2, int(16)> r_4;

#line 265
    uint n2_0 = 0U;


    for(;;)
    {

#line 268
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 268
            break;
        }

#line 269
        uint idx_0 = tid_0 + 32U * n2_0;
        r_4[n2_0] = cmulConj_0(cload_0(data_0, _S21 * 512U + idx_0), cload_0(tmpl_0, _S22 * 512U + idx_0));

#line 268
        n2_0 = n2_0 + 1U;

#line 268
    }

#line 268
    for(;;)
    {

#line 268
        for(;;)
        {



            for(;;)
            {

#line 274
                thread array<uint, int(16)> want_1;

#line 274
                z_1 = 0U;
                for(;;)
                {

#line 275
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 275
                        break;
                    }

#line 275
                    want_1[z_1] = 0U;

#line 275
                    z_1 = z_1 + 1U;

#line 275
                }



                uint lgTB_0 = firstbithigh_0(32U);

#line 279
                _S19 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(512U);

                uint _S23 = tid_0 & 31U;

                dft16_0(&r_4);

#line 284
                k2_1 = 0U;
                for(;;)
                {

#line 285
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 285
                        break;
                    }

#line 286
                    float ang_0 = 6.28318548202514648f * float(_S23 * k2_1) / 512.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cos(ang_0), sin(ang_0)));

#line 285
                    k2_1 = k2_1 + 1U;

#line 285
                }

#line 292
                uint _S24 = max(32U, 1U);

#line 292
                uint _S25 = 16U / _S24;
                uint _S26 = max(2U, 1U);

#line 293
                _S20 = _S26;
                uint _S27 = tid_0 / _S26;

#line 294
                uint _S28 = tid_0 % _S26;

#line 294
                d_2 = 0U;
                for(;;)
                {

#line 295
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 295
                        break;
                    }

#line 296
                    uint j_1 = d_2 / _S24;

#line 296
                    uint m_0 = d_2 % _S24;
                    want_1[d_2] = _S27 * 32U + _S28 + _S26 * d_2;

#line 295
                    d_2 = d_2 + 1U;

#line 295
                }

#line 295
                thread array<uint, int(16)> _S29 = want_1;

#line 295
                exchange_0(&r_4, &_S29, lgLn_0, lgTB_0, kernelContext_3);

#line 273
                break;
            }

#line 273
            break;
        }

#line 273
        for(;;)
        {

#line 273
            for(;;)
            {

#line 274
                thread array<uint, int(16)> want_2;

#line 274
                z_1 = 0U;
                for(;;)
                {

#line 275
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 275
                        break;
                    }

#line 275
                    want_2[z_1] = 0U;

#line 275
                    z_1 = z_1 + 1U;

#line 275
                }



                uint lgTB_1 = firstbithigh_0(2U);

                uint _S30 = tid_0 >> lgTB_1;
                uint _S31 = tid_0 & 1U;

                dft16_0(&r_4);

#line 284
                k2_1 = 0U;
                for(;;)
                {

#line 285
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 285
                        break;
                    }

#line 286
                    float ang_1 = 6.28318548202514648f * float(_S31 * k2_1) / 32.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cos(ang_1), sin(ang_1)));

#line 285
                    k2_1 = k2_1 + 1U;

#line 285
                }

#line 292
                uint _S32 = 16U / _S20;
                uint _S33 = max(0U, 1U);
                uint _S34 = tid_0 / _S33;

#line 294
                uint _S35 = tid_0 % _S33;

#line 294
                d_2 = 0U;
                for(;;)
                {

#line 295
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 295
                        break;
                    }

#line 296
                    uint j_2 = d_2 / _S20;

#line 296
                    uint m_1 = d_2 % _S20;
                    want_2[d_2] = _S30 * 32U + (_S31 * _S32 + j_2) * 2U + m_1;

#line 295
                    d_2 = d_2 + 1U;

#line 295
                }

#line 295
                thread array<uint, int(16)> _S36 = want_2;

#line 295
                exchange_0(&r_4, &_S36, _S19, lgTB_1, kernelContext_3);

#line 273
                break;
            }

#line 273
            break;
        }

#line 273
        break;
    }

#line 303
    innermost_0(&r_4);

#line 316
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 316
    uint b_7 = tid_0;
    for(;;)
    {

#line 317
        if(b_7 < nbins_1)
        {
        }
        else
        {

#line 317
            break;
        }

#line 317
        (*kernelContext_3->stg_0)[b_7] = thrBits_1;

#line 317
        b_7 = b_7 + 32U;

#line 317
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;
    thread array<uint, int(16)> myBin_0;

#line 321
    uint i_5 = 0U;
    for(;;)
    {

#line 322
        if(i_5 < 16U)
        {
        }
        else
        {

#line 322
            break;
        }

#line 323
        uint idx_1 = slotToIndex_0(tid_0 * 16U + i_5);
        if(idx_1 >= winStart_1)
        {

#line 324
            live_0 = idx_1 < winEnd_1;

#line 324
        }
        else
        {

#line 324
            live_0 = false;

#line 324
        }



        float _rx_0 = r_4[i_5].x;

#line 328
        float _ry_0 = r_4[i_5].y;
        if(live_0)
        {

#line 329
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 329
        }
        else
        {

#line 329
            n2_0 = 0U;

#line 329
        }

#line 329
        myMag_0[i_5] = n2_0;
        uint off_0 = idx_1 - winStart_1;



        if(live_0)
        {

#line 334
            if(binShift_1 >= int(0))
            {

#line 334
                z_1 = off_0 >> uint(binShift_1);

#line 334
            }
            else
            {

#line 334
                uint _S37 = off_0 / binsize_1;

#line 334
                z_1 = _S37;

#line 334
            }

#line 334
        }
        else
        {

#line 334
            z_1 = 0U;

#line 334
        }

#line 334
        myBin_0[i_5] = z_1;

#line 334
        bool _S38;

        if(nbins_1 > 1U)
        {

#line 336
            _S38 = (myMag_0[i_5]) > thrBits_1;

#line 336
        }
        else
        {

#line 336
            _S38 = false;

#line 336
        }

#line 336
        if(_S38)
        {

#line 337
            uint _S39 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[myBin_0[i_5]])), myMag_0[i_5], memory_order_relaxed);

#line 336
        }

#line 322
        i_5 = i_5 + 1U;

#line 322
    }

#line 345
    if(nbins_1 == 1U)
    {

#line 345
        i_5 = 0U;

#line 345
        uint bestBits_0 = thrBits_1;

        for(;;)
        {

#line 347
            if(i_5 < 16U)
            {
            }
            else
            {

#line 347
                break;
            }

#line 347
            uint _S40 = max(bestBits_0, myMag_0[i_5]);

#line 347
            i_5 = i_5 + 1U;

#line 347
            bestBits_0 = _S40;

#line 347
        }
        uint wm_0 = simd_max(bestBits_0);
        bool _S41 = simd_is_first();

#line 349
        if(_S41)
        {

#line 349
            live_0 = wm_0 > thrBits_1;

#line 349
        }
        else
        {

#line 349
            live_0 = false;

#line 349
        }

#line 349
        if(live_0)
        {

#line 349
            uint _S42 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[int(0)])), wm_0, memory_order_relaxed);

#line 349
        }

#line 345
    }

#line 351
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 351
    i_5 = 0U;

#line 356
    for(;;)
    {

#line 356
        if(i_5 < 16U)
        {
        }
        else
        {

#line 356
            break;
        }

#line 357
        if((myMag_0[i_5]) > thrBits_1)
        {

#line 357
            live_0 = ((*kernelContext_3->stg_0)[myBin_0[i_5]]) == myMag_0[i_5];

#line 357
        }
        else
        {

#line 357
            live_0 = false;

#line 357
        }

#line 357
        if(live_0)
        {

#line 358
            uint o_1 = pair_0 * nbins_1 + myBin_0[i_5];
            *(peakIdx_0+o_1) = int(slotToIndex_0(tid_0 * 16U + i_5));

#line 359
            *(peakVal_0+o_1) = packed_float2(float2(r_4[i_5].x, r_4[i_5].y)) ;

#line 357
        }

#line 356
        i_5 = i_5 + 1U;

#line 356
    }

#line 356
    b_7 = tid_0;

#line 365
    for(;;)
    {

#line 365
        if(b_7 < nbins_1)
        {
        }
        else
        {

#line 365
            break;
        }

#line 366
        if(((*kernelContext_3->stg_0)[b_7]) == thrBits_1)
        {

#line 367
            uint o_2 = pair_0 * nbins_1 + b_7;
            *(peakIdx_0+o_2) = int(-1);

#line 368
            *(peakVal_0+o_2) = packed_float2(float2(0.0f, 0.0f)) ;

#line 366
        }

#line 365
        b_7 = b_7 + 32U;

#line 365
    }

#line 372
    return;
}


#line 400
[[kernel]] void gatedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]], packed_float2 device* entryPointParams_coarse_1 [[buffer(5)]])
{

#line 400
    thread KernelContext_0 kernelContext_4;

#line 400
    (&kernelContext_4)->entryPointParams_0 = entryPointParams_1;

#line 400
    (&kernelContext_4)->entryPointParams_data_0 = entryPointParams_data_1;

#line 400
    (&kernelContext_4)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 400
    (&kernelContext_4)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 400
    (&kernelContext_4)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 400
    (&kernelContext_4)->entryPointParams_coarse_0 = entryPointParams_coarse_1;

#line 400
    threadgroup array<uint, int(1024)> stg_1;

#line 400
    (&kernelContext_4)->stg_0 = &stg_1;

#line 409
    uint pair_1 = gid_0.x;

#line 409
    uint tid_1 = lid_0.x;

#line 416
    if((length(float2(*(entryPointParams_coarse_1+pair_1)) )) < (entryPointParams_1->thr_0))
    {

#line 416
        uint b_8 = tid_1;
        for(;;)
        {

#line 417
            if(b_8 < ((&kernelContext_4)->entryPointParams_0->nbins_0))
            {
            }
            else
            {

#line 417
                break;
            }

#line 418
            uint o_3 = pair_1 * (&kernelContext_4)->entryPointParams_0->nbins_0 + b_8;
            *((&kernelContext_4)->entryPointParams_peakIdx_0+o_3) = int(-1);

#line 419
            *((&kernelContext_4)->entryPointParams_peakVal_0+o_3) = packed_float2(float2(0.0f, 0.0f)) ;

#line 417
            b_8 = b_8 + 32U;

#line 417
        }

#line 422
        return;
    }

#line 422
    filterPair_0(pair_1, tid_1, (&kernelContext_4)->entryPointParams_data_0, (&kernelContext_4)->entryPointParams_tmpl_0, (&kernelContext_4)->entryPointParams_peakIdx_0, (&kernelContext_4)->entryPointParams_peakVal_0, (&kernelContext_4)->entryPointParams_0->ntmpl_0, (&kernelContext_4)->entryPointParams_0->winStart_0, (&kernelContext_4)->entryPointParams_0->winEnd_0, (&kernelContext_4)->entryPointParams_0->binsize_0, (&kernelContext_4)->entryPointParams_0->binShift_0, (&kernelContext_4)->entryPointParams_0->nbins_0, (&kernelContext_4)->entryPointParams_0->thrBits_0, &kernelContext_4);



    return;
}

