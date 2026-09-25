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


#line 116 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_4096_fusedTierB.slang"
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


#line 190
void dft16_1(array<float2, int(16)> thread* r_1)
{
    float2 W1_1 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_1 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_1 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_1 = float2(0.0f, 1.0f);
    float2 W6_1 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_1 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 197
    uint n1_1 = 0U;
    for(;;)
    {

#line 198
        if(n1_1 < 4U)
        {
        }
        else
        {

#line 198
            break;
        }

#line 198
        r4_0(&(*r_1)[n1_1], &(*r_1)[n1_1 + 4U], &(*r_1)[n1_1 + 8U], &(*r_1)[n1_1 + 12U]);

#line 198
        n1_1 = n1_1 + 1U;

#line 198
    }
    (*r_1)[int(5)] = cmul_0((*r_1)[int(5)], W1_1);

#line 199
    (*r_1)[int(9)] = cmul_0((*r_1)[int(9)], W2_1);

#line 199
    (*r_1)[int(13)] = cmul_0((*r_1)[int(13)], W3_1);
    (*r_1)[int(6)] = cmul_0((*r_1)[int(6)], W2_1);

#line 200
    (*r_1)[int(10)] = cmul_0((*r_1)[int(10)], W4_1);

#line 200
    (*r_1)[int(14)] = cmul_0((*r_1)[int(14)], W6_1);
    (*r_1)[int(7)] = cmul_0((*r_1)[int(7)], W3_1);

#line 201
    (*r_1)[int(11)] = cmul_0((*r_1)[int(11)], W6_1);

#line 201
    (*r_1)[int(15)] = cmul_0((*r_1)[int(15)], W9_1);

#line 201
    uint k2_1 = 0U;
    for(;;)
    {

#line 202
        if(k2_1 < 4U)
        {
        }
        else
        {

#line 202
            break;
        }

#line 202
        uint _S11 = 4U * k2_1;

#line 202
        r4_0(&(*r_1)[_S11], &(*r_1)[_S11 + 1U], &(*r_1)[_S11 + 2U], &(*r_1)[_S11 + 3U]);

#line 202
        k2_1 = k2_1 + 1U;

#line 202
    }

    float2 t_6 = (*r_1)[int(1)];

#line 204
    (*r_1)[int(1)] = (*r_1)[int(4)];

#line 204
    (*r_1)[int(4)] = t_6;
    float2 t_7 = (*r_1)[int(2)];

#line 205
    (*r_1)[int(2)] = (*r_1)[int(8)];

#line 205
    (*r_1)[int(8)] = t_7;
    float2 t_8 = (*r_1)[int(3)];

#line 206
    (*r_1)[int(3)] = (*r_1)[int(12)];

#line 206
    (*r_1)[int(12)] = t_8;
    float2 t_9 = (*r_1)[int(6)];

#line 207
    (*r_1)[int(6)] = (*r_1)[int(9)];

#line 207
    (*r_1)[int(9)] = t_9;
    float2 t_10 = (*r_1)[int(7)];

#line 208
    (*r_1)[int(7)] = (*r_1)[int(13)];

#line 208
    (*r_1)[int(13)] = t_10;
    float2 t_11 = (*r_1)[int(11)];

#line 209
    (*r_1)[int(11)] = (*r_1)[int(14)];

#line 209
    (*r_1)[int(14)] = t_11;
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


#line 140 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_4096_fusedTierB.slang"
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


#line 140
void stgPut_0(uint i_1, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 140
    uint _S12 = 2U * i_1;

#line 140
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S12] = (as_type<uint>((v_0.x)));

#line 140
    (*kernelContext_0->stg_0)[kernelContext_0->_stgBase_0 + _S12 + 1U] = (as_type<uint>((v_0.y)));

#line 140
    return;
}


#line 141
float2 stgGet_0(uint i_2, KernelContext_0 thread* kernelContext_1)
{

#line 141
    uint _S13 = 2U * i_2;

#line 141
    return float2((as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S13]))), (as_type<float>(((*kernelContext_1->stg_0)[kernelContext_1->_stgBase_0 + _S13 + 1U]))));
}


#line 231
void exchange_0(array<float2, int(16)> thread* r_2, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
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
    uint _S14 = (1U << lgSpan_0) - 1U;
    uint _S15 = (1U << lgLen_0) - 1U;

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
            stgPut_0(j_0 * 256U + kernelContext_2->_tid_0, (*r_2)[c_1 * 16U + j_0], kernelContext_2);

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
            uint rem_0 = ((*want_0)[d_1]) & _S15;
            uint i_3 = rem_0 >> lgSpan_0;

#line 253
            uint ln_0 = rem_0 & _S14;
            uint _S16 = c_1 * 16U;

#line 254
            bool _S17;

#line 254
            if(i_3 >= _S16)
            {

#line 254
                _S17 = i_3 < ((c_1 + 1U) * 16U);

#line 254
            }
            else
            {

#line 254
                _S17 = false;

#line 254
            }

#line 254
            if(_S17)
            {

#line 254
                float2 _S18 = stgGet_0((i_3 - _S16) * 256U + (b_4 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S18;

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
        (*r_2)[j_0] = out_0[j_0];

#line 258
        j_0 = j_0 + 1U;

#line 258
    }
    return;
}


#line 215
void innermost_0(array<float2, int(16)> thread* r_3)
{
    dft16_1(r_3);



    return;
}


#line 280
uint lgOf_0(uint i_4)
{

#line 280
    uint _S19;

#line 280
    if(i_4 < 2U)
    {

#line 280
        _S19 = 4U;

#line 280
    }
    else
    {

#line 280
        if(i_4 == 2U)
        {

#line 280
            _S19 = 4U;

#line 280
        }
        else
        {

#line 280
            _S19 = 1U;

#line 280
        }

#line 280
    }

#line 280
    return _S19;
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




void filterPair_0(uint pair_0, uint tid_0, packed_float2 device* data_0, packed_float2 device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint ntmpl_1, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{



    uint z_1;

#line 302
    uint _S20;

#line 302
    uint k2_2;

#line 302
    uint _S21;

#line 302
    uint d_2;

#line 302
    bool live_0;

    kernelContext_3->_tid_0 = tid_0;
    uint _S22 = pair_0 / ntmpl_1;

#line 305
    uint _S23 = pair_0 % ntmpl_1;
    thread array<float2, int(16)> r_4;

#line 306
    uint n2_0 = 0U;


    for(;;)
    {

#line 309
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 309
            break;
        }

#line 310
        uint idx_0 = tid_0 + 256U * n2_0;
        r_4[n2_0] = cmulConj_0(cload_0(data_0, _S22 * 4096U + idx_0), cload_0(tmpl_0, _S23 * 4096U + idx_0));

#line 309
        n2_0 = n2_0 + 1U;

#line 309
    }

#line 309
    for(;;)
    {

#line 309
        for(;;)
        {



            for(;;)
            {

#line 315
                thread array<uint, int(16)> want_1;

#line 315
                z_1 = 0U;
                for(;;)
                {

#line 316
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 316
                        break;
                    }

#line 316
                    want_1[z_1] = 0U;

#line 316
                    z_1 = z_1 + 1U;

#line 316
                }



                uint lgTB_0 = firstbithigh_0(256U);

#line 320
                _S20 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(4096U);

                uint _S24 = tid_0 & 255U;

                dft16_0(&r_4);

#line 325
                k2_2 = 0U;
                for(;;)
                {

#line 326
                    if(k2_2 < 16U)
                    {
                    }
                    else
                    {

#line 326
                        break;
                    }

#line 327
                    float ang_0 = 6.28318548202514648f * float(_S24 * k2_2) / 4096.0f;
                    r_4[k2_2] = cmul_0(r_4[k2_2], float2(cos(ang_0), sin(ang_0)));

#line 326
                    k2_2 = k2_2 + 1U;

#line 326
                }

#line 333
                uint _S25 = max(256U, 1U);

#line 333
                uint _S26 = 16U / _S25;
                uint _S27 = max(16U, 1U);

#line 334
                _S21 = _S27;
                uint _S28 = tid_0 / _S27;

#line 335
                uint _S29 = tid_0 % _S27;

#line 335
                d_2 = 0U;
                for(;;)
                {

#line 336
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 336
                        break;
                    }

#line 337
                    uint j_1 = d_2 / _S25;

#line 337
                    uint m_0 = d_2 % _S25;
                    want_1[d_2] = _S28 * 256U + _S29 + _S27 * d_2;

#line 336
                    d_2 = d_2 + 1U;

#line 336
                }

#line 336
                thread array<uint, int(16)> _S30 = want_1;

#line 336
                exchange_0(&r_4, &_S30, lgLn_0, lgTB_0, kernelContext_3);

#line 314
                break;
            }

#line 314
            break;
        }

#line 314
        for(;;)
        {

#line 314
            for(;;)
            {

#line 315
                thread array<uint, int(16)> want_2;

#line 315
                z_1 = 0U;
                for(;;)
                {

#line 316
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 316
                        break;
                    }

#line 316
                    want_2[z_1] = 0U;

#line 316
                    z_1 = z_1 + 1U;

#line 316
                }



                uint lgTB_1 = firstbithigh_0(16U);

                uint _S31 = tid_0 >> lgTB_1;
                uint _S32 = tid_0 & 15U;

                dft16_0(&r_4);

#line 325
                k2_2 = 0U;
                for(;;)
                {

#line 326
                    if(k2_2 < 16U)
                    {
                    }
                    else
                    {

#line 326
                        break;
                    }

#line 327
                    float ang_1 = 6.28318548202514648f * float(_S32 * k2_2) / 256.0f;
                    r_4[k2_2] = cmul_0(r_4[k2_2], float2(cos(ang_1), sin(ang_1)));

#line 326
                    k2_2 = k2_2 + 1U;

#line 326
                }

#line 333
                uint _S33 = 16U / _S21;
                uint _S34 = max(1U, 1U);
                uint _S35 = tid_0 / _S34;

#line 335
                uint _S36 = tid_0 % _S34;

#line 335
                d_2 = 0U;
                for(;;)
                {

#line 336
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 336
                        break;
                    }

#line 337
                    uint j_2 = d_2 / _S21;

#line 337
                    uint m_1 = d_2 % _S21;
                    want_2[d_2] = _S31 * 256U + (_S32 * _S33 + j_2) * 16U + m_1;

#line 336
                    d_2 = d_2 + 1U;

#line 336
                }

#line 336
                thread array<uint, int(16)> _S37 = want_2;

#line 336
                exchange_0(&r_4, &_S37, _S20, lgTB_1, kernelContext_3);

#line 314
                break;
            }

#line 314
            break;
        }

#line 314
        break;
    }

#line 344
    innermost_0(&r_4);

#line 357
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 357
    uint b_5 = tid_0;

#line 365
    for(;;)
    {

#line 365
        if(b_5 < nbins_1)
        {
        }
        else
        {

#line 365
            break;
        }

#line 365
        (*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_5] = thrBits_1;

#line 365
        b_5 = b_5 + 256U;

#line 365
    }

    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;
    thread array<uint, int(16)> myBin_0;

#line 370
    uint i_5 = 0U;
    for(;;)
    {

#line 371
        if(i_5 < 16U)
        {
        }
        else
        {

#line 371
            break;
        }

#line 372
        uint idx_1 = slotToIndex_0(tid_0 * 16U + i_5);
        if(idx_1 >= winStart_1)
        {

#line 373
            live_0 = idx_1 < winEnd_1;

#line 373
        }
        else
        {

#line 373
            live_0 = false;

#line 373
        }



        float _rx_0 = r_4[i_5].x;

#line 377
        float _ry_0 = r_4[i_5].y;
        if(live_0)
        {

#line 378
            n2_0 = (as_type<uint>((_rx_0 * _rx_0 + _ry_0 * _ry_0)));

#line 378
        }
        else
        {

#line 378
            n2_0 = 0U;

#line 378
        }

#line 378
        myMag_0[i_5] = n2_0;
        uint off_0 = idx_1 - winStart_1;

#line 386
        if(live_0)
        {

#line 386
            if(binShift_1 >= int(0))
            {

#line 386
                z_1 = off_0 >> uint(binShift_1);

#line 386
            }
            else
            {

#line 386
                uint _S38 = off_0 / binsize_1;

#line 386
                z_1 = _S38;

#line 386
            }

#line 386
        }
        else
        {

#line 386
            z_1 = 0U;

#line 386
        }

#line 386
        myBin_0[i_5] = z_1;

#line 386
        bool _S39;



        if(nbins_1 > 1U)
        {

#line 390
            _S39 = (myMag_0[i_5]) > thrBits_1;

#line 390
        }
        else
        {

#line 390
            _S39 = false;

#line 390
        }

#line 390
        if(_S39)
        {

#line 391
            uint _S40 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_5]])), myMag_0[i_5], memory_order_relaxed);

#line 390
        }

#line 371
        i_5 = i_5 + 1U;

#line 371
    }

#line 403
    if(nbins_1 == 1U)
    {

#line 403
        i_5 = 0U;

#line 403
        uint bestBits_0 = thrBits_1;


        for(;;)
        {

#line 406
            if(i_5 < 16U)
            {
            }
            else
            {

#line 406
                break;
            }

#line 406
            uint _S41 = max(bestBits_0, myMag_0[i_5]);

#line 406
            i_5 = i_5 + 1U;

#line 406
            bestBits_0 = _S41;

#line 406
        }

        uint wm_0 = simd_max(bestBits_0);
        bool _S42 = simd_is_first();

#line 409
        if(_S42)
        {

#line 409
            live_0 = wm_0 > thrBits_1;

#line 409
        }
        else
        {

#line 409
            live_0 = false;

#line 409
        }

#line 409
        if(live_0)
        {

#line 409
            uint _S43 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0])), wm_0, memory_order_relaxed);

#line 409
        }

#line 403
    }

#line 424
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 424
    i_5 = 0U;

#line 429
    for(;;)
    {

#line 429
        if(i_5 < 16U)
        {
        }
        else
        {

#line 429
            break;
        }



        if((myMag_0[i_5]) > thrBits_1)
        {

#line 434
            live_0 = ((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + myBin_0[i_5]]) == myMag_0[i_5];

#line 434
        }
        else
        {

#line 434
            live_0 = false;

#line 434
        }

#line 434
        if(live_0)
        {

#line 435
            uint o_0 = pair_0 * nbins_1 + myBin_0[i_5];

            *(peakIdx_0+o_0) = int(slotToIndex_0(tid_0 * 16U + i_5));

#line 437
            *(peakVal_0+o_0) = packed_float2(float2(r_4[i_5].x, r_4[i_5].y)) ;

#line 434
        }

#line 429
        i_5 = i_5 + 1U;

#line 429
    }

#line 429
    b_5 = tid_0;

#line 448
    for(;;)
    {

#line 448
        if(b_5 < nbins_1)
        {
        }
        else
        {

#line 448
            break;
        }

#line 449
        if(((*kernelContext_3->stg_0)[kernelContext_3->_stgBase_0 + b_5]) == thrBits_1)
        {

#line 450
            uint o_1 = pair_0 * nbins_1 + b_5;

            *(peakIdx_0+o_1) = int(-1);

#line 452
            *(peakVal_0+o_1) = packed_float2(float2(0.0f, 0.0f)) ;

#line 449
        }

#line 448
        b_5 = b_5 + 256U;

#line 448
    }

#line 456
    return;
}

[[kernel]] void fusedTierB(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]])
{

#line 459
    thread KernelContext_0 kernelContext_4;

#line 459
    (&kernelContext_4)->entryPointParams_0 = entryPointParams_1;

#line 459
    (&kernelContext_4)->entryPointParams_data_0 = entryPointParams_data_1;

#line 459
    (&kernelContext_4)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 459
    (&kernelContext_4)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 459
    (&kernelContext_4)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 459
    threadgroup array<uint, int(8192)> stg_1;

#line 459
    (&kernelContext_4)->stg_0 = &stg_1;

#line 476
    uint _pr_0 = gid_0.x;

#line 476
    uint _t_0 = lid_0.x;
    (&kernelContext_4)->_stgBase_0 = 0U;

#line 477
    filterPair_0(_pr_0, _t_0, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_4);

#line 485
    return;
}

