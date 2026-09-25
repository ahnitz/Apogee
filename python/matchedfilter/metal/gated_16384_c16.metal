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


#line 81 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_16384_gatedTierB_c16.slang"
float2 cload_0(uint device* b_0, uint i_0)
{

#line 82
    uint p_0 = b_0[i_0];

#line 82
    return float2((as_type<half>((ushort)((p_0 & 65535U)))), (as_type<half>((ushort)((p_0 >> 16U)))));
}


#line 99
float2 cmulConj_0(float2 a_0, float2 b_1)
{

#line 99
    float _S2 = a_0.x;

#line 99
    float _S3 = b_1.x;

#line 99
    float _S4 = a_0.y;

#line 99
    float _S5 = b_1.y;

#line 99
    return float2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 101
void r4_0(float2 thread* a_1, float2 thread* b_2, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_1 + *c_0;

#line 103
    float2 t1_0 = *a_1 - *c_0;

#line 103
    float2 t2_0 = *b_2 + *d_0;

#line 103
    float2 t3_0 = *b_2 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_1 = t0_0 + t2_0;

#line 105
    *b_2 = t1_0 + j3_0;

#line 105
    *c_0 = t0_0 - t2_0;

#line 105
    *d_0 = t1_0 - j3_0;
    return;
}


#line 98
float2 cmul_0(float2 a_2, float2 b_3)
{

#line 98
    float _S6 = a_2.x;

#line 98
    float _S7 = b_3.x;

#line 98
    float _S8 = a_2.y;

#line 98
    float _S9 = b_3.y;

#line 98
    return float2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 137
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 144
    uint n1_0 = 0U;
    for(;;)
    {

#line 145
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 145
            break;
        }

#line 145
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 145
        n1_0 = n1_0 + 1U;

#line 145
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 146
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 146
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 147
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 147
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 148
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 148
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 148
    uint k2_0 = 0U;
    for(;;)
    {

#line 149
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 149
            break;
        }

#line 149
        uint _S10 = 4U * k2_0;

#line 149
        r4_0(&(*r_0)[_S10], &(*r_0)[_S10 + 1U], &(*r_0)[_S10 + 2U], &(*r_0)[_S10 + 3U]);

#line 149
        k2_0 = k2_0 + 1U;

#line 149
    }

    float2 t_0 = (*r_0)[int(1)];

#line 151
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 151
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 152
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 152
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 153
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 153
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 154
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 154
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 155
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 155
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 156
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 156
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
    float thr_0;
};


#line 88 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_16384_gatedTierB_c16.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    uint device* entryPointParams_data_0;
    uint device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    packed_float2 device* entryPointParams_coarse_0;
    uint _tid_0;
    array<uint, int(16384)> threadgroup* stg_0;
};


#line 88
void stgPut_0(uint i_1, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 88
    uint _S11 = 2U * i_1;

#line 88
    (*kernelContext_0->stg_0)[_S11] = (as_type<uint>((v_0.x)));

#line 88
    (*kernelContext_0->stg_0)[_S11 + 1U] = (as_type<uint>((v_0.y)));

#line 88
    return;
}


#line 89
float2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 89
    uint _S12 = 2U * i_2;

#line 89
    return float2((as_type<float>(((*kernelContext_1->stg_0)[_S12]))), (as_type<float>(((*kernelContext_1->stg_0)[_S12 + 1U]))));
}


#line 178
void exchange_0(array<float2, int(16)> thread* r_1, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 178
    uint j_0;

#line 189
    thread array<float2, int(16)> out_0;

#line 189
    uint z_0 = 0U;
    for(;;)
    {

#line 190
        if(z_0 < 16U)
        {
        }
        else
        {

#line 190
            break;
        }

#line 190
        out_0[z_0] = float2(0.0f, 0.0f);

#line 190
        z_0 = z_0 + 1U;

#line 190
    }
    uint _S13 = (1U << lgSpan_0) - 1U;
    uint _S14 = (1U << lgLen_0) - 1U;

#line 192
    uint c_1 = 0U;
    for(;;)
    {

#line 193
        if(c_1 < 2U)
        {
        }
        else
        {

#line 193
            break;
        }

#line 194
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 194
        j_0 = 0U;
        for(;;)
        {

#line 195
            if(j_0 < 8U)
            {
            }
            else
            {

#line 195
                break;
            }

#line 195
            stgPut_0(j_0 * 1024U + kernelContext_2->_tid_0, (*r_1)[c_1 * 8U + j_0], kernelContext_2);

#line 195
            j_0 = j_0 + 1U;

#line 195
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 196
        uint d_1 = 0U;
        for(;;)
        {

#line 197
            if(d_1 < 16U)
            {
            }
            else
            {

#line 197
                break;
            }
            uint b_4 = ((*want_0)[d_1]) >> lgLen_0;

#line 199
            uint rem_0 = ((*want_0)[d_1]) & _S14;
            uint i_3 = rem_0 >> lgSpan_0;

#line 200
            uint ln_0 = rem_0 & _S13;
            uint _S15 = c_1 * 8U;

#line 201
            bool _S16;

#line 201
            if(i_3 >= _S15)
            {

#line 201
                _S16 = i_3 < ((c_1 + 1U) * 8U);

#line 201
            }
            else
            {

#line 201
                _S16 = false;

#line 201
            }

#line 201
            if(_S16)
            {

#line 201
                float2 _S17 = stgGet_0((i_3 - _S15) * 1024U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S17;

#line 201
            }

#line 197
            d_1 = d_1 + 1U;

#line 197
        }

#line 193
        c_1 = c_1 + 1U;

#line 193
    }

#line 193
    j_0 = 0U;

#line 205
    for(;;)
    {

#line 205
        if(j_0 < 16U)
        {
        }
        else
        {

#line 205
            break;
        }

#line 205
        (*r_1)[j_0] = out_0[j_0];

#line 205
        j_0 = j_0 + 1U;

#line 205
    }
    return;
}


#line 116
void dft4_0(array<float2, int(16)> thread* r_2, uint o_0)
{
    r4_0(&(*r_2)[o_0], &(*r_2)[o_0 + 1U], &(*r_2)[o_0 + 2U], &(*r_2)[o_0 + 3U]);
    float2 t_6 = (*r_2)[o_0 + 1U];

#line 119
    (*r_2)[o_0 + 1U] = (*r_2)[o_0 + 2U];

#line 119
    (*r_2)[o_0 + 2U] = t_6;
    return;
}


#line 162
void innermost_0(array<float2, int(16)> thread* r_3)
{

#line 162
    uint b_5 = 0U;



    for(;;)
    {

#line 166
        if(b_5 < 4U)
        {
        }
        else
        {

#line 166
            break;
        }

#line 166
        dft4_0(r_3, b_5 * 4U);

#line 166
        b_5 = b_5 + 1U;

#line 166
    }

    return;
}


#line 227
uint lgOf_0(uint i_4)
{

#line 227
    uint _S18;

#line 227
    if(i_4 < 3U)
    {

#line 227
        _S18 = 4U;

#line 227
    }
    else
    {

#line 227
        _S18 = 1U;

#line 227
    }

#line 227
    return _S18;
}


#line 229
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(4U);

    uint x_0 = slot_0 >> lg_0;

#line 233
    uint lg_1 = lgOf_0(3U);

    uint x_1 = x_0 >> lg_1;

#line 233
    uint lg_2 = lgOf_0(2U);

    uint x_2 = x_1 >> lg_2;

#line 233
    uint lg_3 = lgOf_0(1U);

#line 233
    uint lg_4 = lgOf_0(0U);

#line 238
    return (((((((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | (x_1 & ((1U << lg_2) - 1U))) << lg_3) | (x_2 & ((1U << lg_3) - 1U))) << lg_4) | ((x_2 >> lg_3) & ((1U << lg_4) - 1U));
}




void filterPair_0(uint pair_0, uint tid_0, uint device* data_0, uint device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint ntmpl_1, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{



    uint z_1;

#line 249
    uint _S19;

#line 249
    uint k2_1;

#line 249
    uint _S20;

#line 249
    uint d_2;

#line 249
    uint _S21;

#line 249
    uint _S22;

#line 249
    bool live_0;

    kernelContext_3->_tid_0 = tid_0;
    uint _S23 = pair_0 / ntmpl_1;

#line 252
    uint _S24 = pair_0 % ntmpl_1;
    thread array<float2, int(16)> r_4;

#line 253
    uint n2_0 = 0U;


    for(;;)
    {

#line 256
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 256
            break;
        }

#line 257
        uint idx_0 = tid_0 + 1024U * n2_0;
        r_4[n2_0] = cmulConj_0(cload_0(data_0, _S23 * 16384U + idx_0), cload_0(tmpl_0, _S24 * 16384U + idx_0));

#line 256
        n2_0 = n2_0 + 1U;

#line 256
    }

#line 256
    for(;;)
    {

#line 256
        for(;;)
        {



            for(;;)
            {

#line 262
                thread array<uint, int(16)> want_1;

#line 262
                z_1 = 0U;
                for(;;)
                {

#line 263
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 263
                        break;
                    }

#line 263
                    want_1[z_1] = 0U;

#line 263
                    z_1 = z_1 + 1U;

#line 263
                }



                uint lgTB_0 = firstbithigh_0(1024U);

#line 267
                _S19 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(16384U);

                uint _S25 = tid_0 & 1023U;

                dft16_0(&r_4);

#line 272
                k2_1 = 0U;
                for(;;)
                {

#line 273
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 273
                        break;
                    }

#line 274
                    float ang_0 = 6.28318548202514648f * float(_S25 * k2_1) / 16384.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cos(ang_0), sin(ang_0)));

#line 273
                    k2_1 = k2_1 + 1U;

#line 273
                }

#line 280
                uint _S26 = max(1024U, 1U);

#line 280
                uint _S27 = 16U / _S26;
                uint _S28 = max(64U, 1U);

#line 281
                _S20 = _S28;
                uint _S29 = tid_0 / _S28;

#line 282
                uint _S30 = tid_0 % _S28;

#line 282
                d_2 = 0U;
                for(;;)
                {

#line 283
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 283
                        break;
                    }

#line 284
                    uint j_1 = d_2 / _S26;

#line 284
                    uint m_0 = d_2 % _S26;
                    want_1[d_2] = _S29 * 1024U + _S30 + _S28 * d_2;

#line 283
                    d_2 = d_2 + 1U;

#line 283
                }

#line 283
                thread array<uint, int(16)> _S31 = want_1;

#line 283
                exchange_0(&r_4, &_S31, lgLn_0, lgTB_0, kernelContext_3);

#line 261
                break;
            }

#line 261
            break;
        }

#line 261
        for(;;)
        {

#line 261
            for(;;)
            {

#line 262
                thread array<uint, int(16)> want_2;

#line 262
                z_1 = 0U;
                for(;;)
                {

#line 263
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 263
                        break;
                    }

#line 263
                    want_2[z_1] = 0U;

#line 263
                    z_1 = z_1 + 1U;

#line 263
                }



                uint lgTB_1 = firstbithigh_0(64U);

#line 267
                _S21 = lgTB_1;


                uint _S32 = tid_0 & 63U;

                dft16_0(&r_4);

#line 272
                k2_1 = 0U;
                for(;;)
                {

#line 273
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 273
                        break;
                    }

#line 274
                    float ang_1 = 6.28318548202514648f * float(_S32 * k2_1) / 1024.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cos(ang_1), sin(ang_1)));

#line 273
                    k2_1 = k2_1 + 1U;

#line 273
                }

#line 280
                uint _S33 = 16U / _S20;
                uint _S34 = max(4U, 1U);

#line 281
                _S22 = _S34;
                uint _S35 = tid_0 / _S34;

#line 282
                uint _S36 = tid_0 % _S34;

#line 282
                d_2 = 0U;
                for(;;)
                {

#line 283
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 283
                        break;
                    }

#line 284
                    uint j_2 = d_2 / _S20;

#line 284
                    uint m_1 = d_2 % _S20;
                    want_2[d_2] = _S35 * 64U + _S36 + _S34 * d_2;

#line 283
                    d_2 = d_2 + 1U;

#line 283
                }

#line 283
                thread array<uint, int(16)> _S37 = want_2;

#line 283
                exchange_0(&r_4, &_S37, _S19, lgTB_1, kernelContext_3);

#line 261
                break;
            }

#line 261
            break;
        }

#line 261
        for(;;)
        {

#line 261
            for(;;)
            {

#line 262
                thread array<uint, int(16)> want_3;

#line 262
                z_1 = 0U;
                for(;;)
                {

#line 263
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 263
                        break;
                    }

#line 263
                    want_3[z_1] = 0U;

#line 263
                    z_1 = z_1 + 1U;

#line 263
                }



                uint lgTB_2 = firstbithigh_0(4U);

                uint _S38 = tid_0 >> lgTB_2;
                uint _S39 = tid_0 & 3U;

                dft16_0(&r_4);

#line 272
                k2_1 = 0U;
                for(;;)
                {

#line 273
                    if(k2_1 < 16U)
                    {
                    }
                    else
                    {

#line 273
                        break;
                    }

#line 274
                    float ang_2 = 6.28318548202514648f * float(_S39 * k2_1) / 64.0f;
                    r_4[k2_1] = cmul_0(r_4[k2_1], float2(cos(ang_2), sin(ang_2)));

#line 273
                    k2_1 = k2_1 + 1U;

#line 273
                }

#line 280
                uint _S40 = 16U / _S22;
                uint _S41 = max(0U, 1U);
                uint _S42 = tid_0 / _S41;

#line 282
                uint _S43 = tid_0 % _S41;

#line 282
                d_2 = 0U;
                for(;;)
                {

#line 283
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 283
                        break;
                    }

#line 284
                    uint j_3 = d_2 / _S22;

#line 284
                    uint m_2 = d_2 % _S22;
                    want_3[d_2] = _S38 * 64U + (_S39 * _S40 + j_3) * 4U + m_2;

#line 283
                    d_2 = d_2 + 1U;

#line 283
                }

#line 283
                thread array<uint, int(16)> _S44 = want_3;

#line 283
                exchange_0(&r_4, &_S44, _S21, lgTB_2, kernelContext_3);

#line 261
                break;
            }

#line 261
            break;
        }

#line 261
        break;
    }

#line 291
    innermost_0(&r_4);

#line 304
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 304
    uint b_6 = tid_0;
    for(;;)
    {

#line 305
        if(b_6 < nbins_1)
        {
        }
        else
        {

#line 305
            break;
        }

#line 305
        (*kernelContext_3->stg_0)[b_6] = thrBits_1;

#line 305
        b_6 = b_6 + 1024U;

#line 305
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;
    thread array<uint, int(16)> myBin_0;

#line 309
    uint i_5 = 0U;
    for(;;)
    {

#line 310
        if(i_5 < 16U)
        {
        }
        else
        {

#line 310
            break;
        }

#line 311
        uint idx_1 = slotToIndex_0(tid_0 * 16U + i_5);
        if(idx_1 >= winStart_1)
        {

#line 312
            live_0 = idx_1 < winEnd_1;

#line 312
        }
        else
        {

#line 312
            live_0 = false;

#line 312
        }



        if(live_0)
        {

#line 316
            n2_0 = (as_type<uint>((r_4[i_5].x * r_4[i_5].x + r_4[i_5].y * r_4[i_5].y)));

#line 316
        }
        else
        {

#line 316
            n2_0 = 0U;

#line 316
        }

#line 316
        myMag_0[i_5] = n2_0;
        uint off_0 = idx_1 - winStart_1;



        if(live_0)
        {

#line 321
            if(binShift_1 >= int(0))
            {

#line 321
                z_1 = off_0 >> uint(binShift_1);

#line 321
            }
            else
            {

#line 321
                uint _S45 = off_0 / binsize_1;

#line 321
                z_1 = _S45;

#line 321
            }

#line 321
        }
        else
        {

#line 321
            z_1 = 0U;

#line 321
        }

#line 321
        myBin_0[i_5] = z_1;

#line 321
        bool _S46;

        if(nbins_1 > 1U)
        {

#line 323
            _S46 = (myMag_0[i_5]) > thrBits_1;

#line 323
        }
        else
        {

#line 323
            _S46 = false;

#line 323
        }

#line 323
        if(_S46)
        {

#line 324
            uint _S47 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[myBin_0[i_5]])), myMag_0[i_5], memory_order_relaxed);

#line 323
        }

#line 310
        i_5 = i_5 + 1U;

#line 310
    }

#line 332
    if(nbins_1 == 1U)
    {

#line 332
        i_5 = 0U;

#line 332
        uint bestBits_0 = thrBits_1;

        for(;;)
        {

#line 334
            if(i_5 < 16U)
            {
            }
            else
            {

#line 334
                break;
            }

#line 334
            uint _S48 = max(bestBits_0, myMag_0[i_5]);

#line 334
            i_5 = i_5 + 1U;

#line 334
            bestBits_0 = _S48;

#line 334
        }
        uint wm_0 = simd_max(bestBits_0);
        bool _S49 = simd_is_first();

#line 336
        if(_S49)
        {

#line 336
            live_0 = wm_0 > thrBits_1;

#line 336
        }
        else
        {

#line 336
            live_0 = false;

#line 336
        }

#line 336
        if(live_0)
        {

#line 336
            uint _S50 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[int(0)])), wm_0, memory_order_relaxed);

#line 336
        }

#line 332
    }

#line 338
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 338
    i_5 = 0U;

#line 343
    for(;;)
    {

#line 343
        if(i_5 < 16U)
        {
        }
        else
        {

#line 343
            break;
        }

#line 344
        if((myMag_0[i_5]) > thrBits_1)
        {

#line 344
            live_0 = ((*kernelContext_3->stg_0)[myBin_0[i_5]]) == myMag_0[i_5];

#line 344
        }
        else
        {

#line 344
            live_0 = false;

#line 344
        }

#line 344
        if(live_0)
        {

#line 345
            uint o_1 = pair_0 * nbins_1 + myBin_0[i_5];
            *(peakIdx_0+o_1) = int(slotToIndex_0(tid_0 * 16U + i_5));

#line 346
            *(peakVal_0+o_1) = packed_float2(r_4[i_5]) ;

#line 344
        }

#line 343
        i_5 = i_5 + 1U;

#line 343
    }

#line 343
    b_6 = tid_0;

#line 352
    for(;;)
    {

#line 352
        if(b_6 < nbins_1)
        {
        }
        else
        {

#line 352
            break;
        }

#line 353
        if(((*kernelContext_3->stg_0)[b_6]) == thrBits_1)
        {

#line 354
            uint o_2 = pair_0 * nbins_1 + b_6;
            *(peakIdx_0+o_2) = int(-1);

#line 355
            *(peakVal_0+o_2) = packed_float2(float2(0.0f, 0.0f)) ;

#line 353
        }

#line 352
        b_6 = b_6 + 1024U;

#line 352
    }

#line 359
    return;
}


#line 387
[[kernel]] void gatedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], uint device* entryPointParams_data_1 [[buffer(1)]], uint device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]], packed_float2 device* entryPointParams_coarse_1 [[buffer(5)]])
{

#line 387
    thread KernelContext_0 kernelContext_4;

#line 387
    (&kernelContext_4)->entryPointParams_0 = entryPointParams_1;

#line 387
    (&kernelContext_4)->entryPointParams_data_0 = entryPointParams_data_1;

#line 387
    (&kernelContext_4)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 387
    (&kernelContext_4)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 387
    (&kernelContext_4)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 387
    (&kernelContext_4)->entryPointParams_coarse_0 = entryPointParams_coarse_1;

#line 387
    threadgroup array<uint, int(16384)> stg_1;

#line 387
    (&kernelContext_4)->stg_0 = &stg_1;

#line 396
    uint pair_1 = gid_0.x;

#line 396
    uint tid_1 = lid_0.x;

#line 403
    if((length(float2(*(entryPointParams_coarse_1+pair_1)) )) < (entryPointParams_1->thr_0))
    {

#line 403
        uint b_7 = tid_1;
        for(;;)
        {

#line 404
            if(b_7 < ((&kernelContext_4)->entryPointParams_0->nbins_0))
            {
            }
            else
            {

#line 404
                break;
            }

#line 405
            uint o_3 = pair_1 * (&kernelContext_4)->entryPointParams_0->nbins_0 + b_7;
            *((&kernelContext_4)->entryPointParams_peakIdx_0+o_3) = int(-1);

#line 406
            *((&kernelContext_4)->entryPointParams_peakVal_0+o_3) = packed_float2(float2(0.0f, 0.0f)) ;

#line 404
            b_7 = b_7 + 1024U;

#line 404
        }

#line 409
        return;
    }

#line 409
    filterPair_0(pair_1, tid_1, (&kernelContext_4)->entryPointParams_data_0, (&kernelContext_4)->entryPointParams_tmpl_0, (&kernelContext_4)->entryPointParams_peakIdx_0, (&kernelContext_4)->entryPointParams_peakVal_0, (&kernelContext_4)->entryPointParams_0->ntmpl_0, (&kernelContext_4)->entryPointParams_0->winStart_0, (&kernelContext_4)->entryPointParams_0->winEnd_0, (&kernelContext_4)->entryPointParams_0->binsize_0, (&kernelContext_4)->entryPointParams_0->binShift_0, (&kernelContext_4)->entryPointParams_0->nbins_0, (&kernelContext_4)->entryPointParams_0->thrBits_0, &kernelContext_4);



    return;
}

