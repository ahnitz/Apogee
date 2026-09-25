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


#line 71 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_4096_refineListed.slang"
float2 cmulConj_0(float2 a_0, float2 b_0)
{

#line 71
    float _S2 = a_0.x;

#line 71
    float _S3 = b_0.x;

#line 71
    float _S4 = a_0.y;

#line 71
    float _S5 = b_0.y;

#line 71
    return float2(_S2 * _S3 + _S4 * _S5, _S4 * _S3 - _S2 * _S5);
}


#line 73
void r4_0(float2 thread* a_1, float2 thread* b_1, float2 thread* c_0, float2 thread* d_0)
{
    float2 t0_0 = *a_1 + *c_0;

#line 75
    float2 t1_0 = *a_1 - *c_0;

#line 75
    float2 t2_0 = *b_1 + *d_0;

#line 75
    float2 t3_0 = *b_1 - *d_0;
    float2 j3_0 = float2(- t3_0.y, t3_0.x);
    *a_1 = t0_0 + t2_0;

#line 77
    *b_1 = t1_0 + j3_0;

#line 77
    *c_0 = t0_0 - t2_0;

#line 77
    *d_0 = t1_0 - j3_0;
    return;
}


#line 70
float2 cmul_0(float2 a_2, float2 b_2)
{

#line 70
    float _S6 = a_2.x;

#line 70
    float _S7 = b_2.x;

#line 70
    float _S8 = a_2.y;

#line 70
    float _S9 = b_2.y;

#line 70
    return float2(_S6 * _S7 - _S8 * _S9, _S6 * _S9 + _S8 * _S7);
}


#line 109
void dft16_0(array<float2, int(16)> thread* r_0)
{
    float2 W1_0 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_0 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_0 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_0 = float2(0.0f, 1.0f);
    float2 W6_0 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_0 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 116
    uint n1_0 = 0U;
    for(;;)
    {

#line 117
        if(n1_0 < 4U)
        {
        }
        else
        {

#line 117
            break;
        }

#line 117
        r4_0(&(*r_0)[n1_0], &(*r_0)[n1_0 + 4U], &(*r_0)[n1_0 + 8U], &(*r_0)[n1_0 + 12U]);

#line 117
        n1_0 = n1_0 + 1U;

#line 117
    }
    (*r_0)[int(5)] = cmul_0((*r_0)[int(5)], W1_0);

#line 118
    (*r_0)[int(9)] = cmul_0((*r_0)[int(9)], W2_0);

#line 118
    (*r_0)[int(13)] = cmul_0((*r_0)[int(13)], W3_0);
    (*r_0)[int(6)] = cmul_0((*r_0)[int(6)], W2_0);

#line 119
    (*r_0)[int(10)] = cmul_0((*r_0)[int(10)], W4_0);

#line 119
    (*r_0)[int(14)] = cmul_0((*r_0)[int(14)], W6_0);
    (*r_0)[int(7)] = cmul_0((*r_0)[int(7)], W3_0);

#line 120
    (*r_0)[int(11)] = cmul_0((*r_0)[int(11)], W6_0);

#line 120
    (*r_0)[int(15)] = cmul_0((*r_0)[int(15)], W9_0);

#line 120
    uint k2_0 = 0U;
    for(;;)
    {

#line 121
        if(k2_0 < 4U)
        {
        }
        else
        {

#line 121
            break;
        }

#line 121
        uint _S10 = 4U * k2_0;

#line 121
        r4_0(&(*r_0)[_S10], &(*r_0)[_S10 + 1U], &(*r_0)[_S10 + 2U], &(*r_0)[_S10 + 3U]);

#line 121
        k2_0 = k2_0 + 1U;

#line 121
    }

    float2 t_0 = (*r_0)[int(1)];

#line 123
    (*r_0)[int(1)] = (*r_0)[int(4)];

#line 123
    (*r_0)[int(4)] = t_0;
    float2 t_1 = (*r_0)[int(2)];

#line 124
    (*r_0)[int(2)] = (*r_0)[int(8)];

#line 124
    (*r_0)[int(8)] = t_1;
    float2 t_2 = (*r_0)[int(3)];

#line 125
    (*r_0)[int(3)] = (*r_0)[int(12)];

#line 125
    (*r_0)[int(12)] = t_2;
    float2 t_3 = (*r_0)[int(6)];

#line 126
    (*r_0)[int(6)] = (*r_0)[int(9)];

#line 126
    (*r_0)[int(9)] = t_3;
    float2 t_4 = (*r_0)[int(7)];

#line 127
    (*r_0)[int(7)] = (*r_0)[int(13)];

#line 127
    (*r_0)[int(13)] = t_4;
    float2 t_5 = (*r_0)[int(11)];

#line 128
    (*r_0)[int(11)] = (*r_0)[int(14)];

#line 128
    (*r_0)[int(14)] = t_5;
    return;
}


#line 109
void dft16_1(array<float2, int(16)> thread* r_1)
{
    float2 W1_1 = float2(0.92387950420379639f, 0.38268342614173889f);
    float2 W2_1 = float2(0.70710676908493042f, 0.70710676908493042f);
    float2 W3_1 = float2(0.38268342614173889f, 0.92387950420379639f);
    float2 W4_1 = float2(0.0f, 1.0f);
    float2 W6_1 = float2(-0.70710676908493042f, 0.70710676908493042f);
    float2 W9_1 = float2(-0.92387950420379639f, -0.38268342614173889f);

#line 116
    uint n1_1 = 0U;
    for(;;)
    {

#line 117
        if(n1_1 < 4U)
        {
        }
        else
        {

#line 117
            break;
        }

#line 117
        r4_0(&(*r_1)[n1_1], &(*r_1)[n1_1 + 4U], &(*r_1)[n1_1 + 8U], &(*r_1)[n1_1 + 12U]);

#line 117
        n1_1 = n1_1 + 1U;

#line 117
    }
    (*r_1)[int(5)] = cmul_0((*r_1)[int(5)], W1_1);

#line 118
    (*r_1)[int(9)] = cmul_0((*r_1)[int(9)], W2_1);

#line 118
    (*r_1)[int(13)] = cmul_0((*r_1)[int(13)], W3_1);
    (*r_1)[int(6)] = cmul_0((*r_1)[int(6)], W2_1);

#line 119
    (*r_1)[int(10)] = cmul_0((*r_1)[int(10)], W4_1);

#line 119
    (*r_1)[int(14)] = cmul_0((*r_1)[int(14)], W6_1);
    (*r_1)[int(7)] = cmul_0((*r_1)[int(7)], W3_1);

#line 120
    (*r_1)[int(11)] = cmul_0((*r_1)[int(11)], W6_1);

#line 120
    (*r_1)[int(15)] = cmul_0((*r_1)[int(15)], W9_1);

#line 120
    uint k2_1 = 0U;
    for(;;)
    {

#line 121
        if(k2_1 < 4U)
        {
        }
        else
        {

#line 121
            break;
        }

#line 121
        uint _S11 = 4U * k2_1;

#line 121
        r4_0(&(*r_1)[_S11], &(*r_1)[_S11 + 1U], &(*r_1)[_S11 + 2U], &(*r_1)[_S11 + 3U]);

#line 121
        k2_1 = k2_1 + 1U;

#line 121
    }

    float2 t_6 = (*r_1)[int(1)];

#line 123
    (*r_1)[int(1)] = (*r_1)[int(4)];

#line 123
    (*r_1)[int(4)] = t_6;
    float2 t_7 = (*r_1)[int(2)];

#line 124
    (*r_1)[int(2)] = (*r_1)[int(8)];

#line 124
    (*r_1)[int(8)] = t_7;
    float2 t_8 = (*r_1)[int(3)];

#line 125
    (*r_1)[int(3)] = (*r_1)[int(12)];

#line 125
    (*r_1)[int(12)] = t_8;
    float2 t_9 = (*r_1)[int(6)];

#line 126
    (*r_1)[int(6)] = (*r_1)[int(9)];

#line 126
    (*r_1)[int(9)] = t_9;
    float2 t_10 = (*r_1)[int(7)];

#line 127
    (*r_1)[int(7)] = (*r_1)[int(13)];

#line 127
    (*r_1)[int(13)] = t_10;
    float2 t_11 = (*r_1)[int(11)];

#line 128
    (*r_1)[int(11)] = (*r_1)[int(14)];

#line 128
    (*r_1)[int(14)] = t_11;
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


#line 60 "/home/ahnitz/projects/claude/searchdev/work/peak-fft/python/matchedfilter/metal/mm_4096_refineListed.slang"
struct KernelContext_0
{
    EntryPointParams_0 constant* entryPointParams_0;
    packed_float2 device* entryPointParams_data_0;
    packed_float2 device* entryPointParams_tmpl_0;
    int device* entryPointParams_peakIdx_0;
    packed_float2 device* entryPointParams_peakVal_0;
    uint device* entryPointParams_survivors_0;
    uint _tid_0;
    array<uint, int(8192)> threadgroup* stg_0;
};


#line 60
void stgPut_0(uint i_0, float2 v_0, KernelContext_0 thread* kernelContext_0)
{

#line 60
    uint _S12 = 2U * i_0;

#line 60
    (*kernelContext_0->stg_0)[_S12] = (as_type<uint>((v_0.x)));

#line 60
    (*kernelContext_0->stg_0)[_S12 + 1U] = (as_type<uint>((v_0.y)));

#line 60
    return;
}


#line 61
float2 stgGet_0(uint i_1, KernelContext_0 thread* kernelContext_1)
{

#line 61
    uint _S13 = 2U * i_1;

#line 61
    return float2((as_type<float>(((*kernelContext_1->stg_0)[_S13]))), (as_type<float>(((*kernelContext_1->stg_0)[_S13 + 1U]))));
}


#line 150
void exchange_0(array<float2, int(16)> thread* r_2, const array<uint, int(16)> thread* want_0, uint lgLen_0, uint lgSpan_0, KernelContext_0 thread* kernelContext_2)
{

#line 150
    uint j_0;

#line 161
    thread array<float2, int(16)> out_0;

#line 161
    uint z_0 = 0U;
    for(;;)
    {

#line 162
        if(z_0 < 16U)
        {
        }
        else
        {

#line 162
            break;
        }

#line 162
        out_0[z_0] = float2(0.0f, 0.0f);

#line 162
        z_0 = z_0 + 1U;

#line 162
    }
    uint _S14 = (1U << lgSpan_0) - 1U;
    uint _S15 = (1U << lgLen_0) - 1U;

#line 164
    uint c_1 = 0U;
    for(;;)
    {

#line 165
        if(c_1 < 1U)
        {
        }
        else
        {

#line 165
            break;
        }

#line 166
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 166
        j_0 = 0U;
        for(;;)
        {

#line 167
            if(j_0 < 16U)
            {
            }
            else
            {

#line 167
                break;
            }

#line 167
            stgPut_0(j_0 * 256U + kernelContext_2->_tid_0, (*r_2)[c_1 * 16U + j_0], kernelContext_2);

#line 167
            j_0 = j_0 + 1U;

#line 167
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

#line 168
        uint d_1 = 0U;
        for(;;)
        {

#line 169
            if(d_1 < 16U)
            {
            }
            else
            {

#line 169
                break;
            }
            uint b_3 = ((*want_0)[d_1]) >> lgLen_0;

#line 171
            uint rem_0 = ((*want_0)[d_1]) & _S15;
            uint i_2 = rem_0 >> lgSpan_0;

#line 172
            uint ln_0 = rem_0 & _S14;
            uint _S16 = c_1 * 16U;

#line 173
            bool _S17;

#line 173
            if(i_2 >= _S16)
            {

#line 173
                _S17 = i_2 < ((c_1 + 1U) * 16U);

#line 173
            }
            else
            {

#line 173
                _S17 = false;

#line 173
            }

#line 173
            if(_S17)
            {

#line 173
                float2 _S18 = stgGet_0((i_2 - _S16) * 256U + (b_3 << lgSpan_0) + ln_0, kernelContext_2);
                out_0[d_1] = _S18;

#line 173
            }

#line 169
            d_1 = d_1 + 1U;

#line 169
        }

#line 165
        c_1 = c_1 + 1U;

#line 165
    }

#line 165
    j_0 = 0U;

#line 177
    for(;;)
    {

#line 177
        if(j_0 < 16U)
        {
        }
        else
        {

#line 177
            break;
        }

#line 177
        (*r_2)[j_0] = out_0[j_0];

#line 177
        j_0 = j_0 + 1U;

#line 177
    }
    return;
}


#line 134
void innermost_0(array<float2, int(16)> thread* r_3)
{
    dft16_1(r_3);



    return;
}


#line 199
uint lgOf_0(uint i_3)
{

#line 199
    uint _S19;

#line 199
    if(i_3 < 2U)
    {

#line 199
        _S19 = 4U;

#line 199
    }
    else
    {

#line 199
        if(i_3 == 2U)
        {

#line 199
            _S19 = 4U;

#line 199
        }
        else
        {

#line 199
            _S19 = 1U;

#line 199
        }

#line 199
    }

#line 199
    return _S19;
}


#line 201
uint slotToIndex_0(uint slot_0)
{


    uint lg_0 = lgOf_0(2U);

    uint x_0 = slot_0 >> lg_0;

#line 205
    uint lg_1 = lgOf_0(1U);

#line 205
    uint lg_2 = lgOf_0(0U);

#line 210
    return (((((0U << lg_0) | (slot_0 & ((1U << lg_0) - 1U))) << lg_1) | (x_0 & ((1U << lg_1) - 1U))) << lg_2) | ((x_0 >> lg_1) & ((1U << lg_2) - 1U));
}




void filterPair_0(uint pair_0, uint tid_0, packed_float2 device* data_0, packed_float2 device* tmpl_0, int device* peakIdx_0, packed_float2 device* peakVal_0, uint ntmpl_1, uint winStart_1, uint winEnd_1, uint binsize_1, int binShift_1, uint nbins_1, uint thrBits_1, KernelContext_0 thread* kernelContext_3)
{



    uint z_1;

#line 221
    uint _S20;

#line 221
    uint k2_2;

#line 221
    uint _S21;

#line 221
    uint d_2;

#line 221
    bool live_0;

    kernelContext_3->_tid_0 = tid_0;
    uint _S22 = pair_0 / ntmpl_1;

#line 224
    uint _S23 = pair_0 % ntmpl_1;
    thread array<float2, int(16)> r_4;

#line 225
    uint n2_0 = 0U;


    for(;;)
    {

#line 228
        if(n2_0 < 16U)
        {
        }
        else
        {

#line 228
            break;
        }

#line 229
        uint idx_0 = tid_0 + 256U * n2_0;
        r_4[n2_0] = cmulConj_0(float2(*(data_0+(_S22 * 4096U + idx_0))) , float2(*(tmpl_0+(_S23 * 4096U + idx_0))) );

#line 228
        n2_0 = n2_0 + 1U;

#line 228
    }

#line 228
    for(;;)
    {

#line 228
        for(;;)
        {



            for(;;)
            {

#line 234
                thread array<uint, int(16)> want_1;

#line 234
                z_1 = 0U;
                for(;;)
                {

#line 235
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 235
                        break;
                    }

#line 235
                    want_1[z_1] = 0U;

#line 235
                    z_1 = z_1 + 1U;

#line 235
                }



                uint lgTB_0 = firstbithigh_0(256U);

#line 239
                _S20 = lgTB_0;
                uint lgLn_0 = firstbithigh_0(4096U);

                uint _S24 = tid_0 & 255U;

                dft16_0(&r_4);

#line 244
                k2_2 = 0U;
                for(;;)
                {

#line 245
                    if(k2_2 < 16U)
                    {
                    }
                    else
                    {

#line 245
                        break;
                    }

#line 246
                    float ang_0 = 6.28318548202514648f * float(_S24 * k2_2) / 4096.0f;
                    r_4[k2_2] = cmul_0(r_4[k2_2], float2(cos(ang_0), sin(ang_0)));

#line 245
                    k2_2 = k2_2 + 1U;

#line 245
                }

#line 252
                uint _S25 = max(256U, 1U);

#line 252
                uint _S26 = 16U / _S25;
                uint _S27 = max(16U, 1U);

#line 253
                _S21 = _S27;
                uint _S28 = tid_0 / _S27;

#line 254
                uint _S29 = tid_0 % _S27;

#line 254
                d_2 = 0U;
                for(;;)
                {

#line 255
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 255
                        break;
                    }

#line 256
                    uint j_1 = d_2 / _S25;

#line 256
                    uint m_0 = d_2 % _S25;
                    want_1[d_2] = _S28 * 256U + _S29 + _S27 * d_2;

#line 255
                    d_2 = d_2 + 1U;

#line 255
                }

#line 255
                thread array<uint, int(16)> _S30 = want_1;

#line 255
                exchange_0(&r_4, &_S30, lgLn_0, lgTB_0, kernelContext_3);

#line 233
                break;
            }

#line 233
            break;
        }

#line 233
        for(;;)
        {

#line 233
            for(;;)
            {

#line 234
                thread array<uint, int(16)> want_2;

#line 234
                z_1 = 0U;
                for(;;)
                {

#line 235
                    if(z_1 < 16U)
                    {
                    }
                    else
                    {

#line 235
                        break;
                    }

#line 235
                    want_2[z_1] = 0U;

#line 235
                    z_1 = z_1 + 1U;

#line 235
                }



                uint lgTB_1 = firstbithigh_0(16U);

                uint _S31 = tid_0 >> lgTB_1;
                uint _S32 = tid_0 & 15U;

                dft16_0(&r_4);

#line 244
                k2_2 = 0U;
                for(;;)
                {

#line 245
                    if(k2_2 < 16U)
                    {
                    }
                    else
                    {

#line 245
                        break;
                    }

#line 246
                    float ang_1 = 6.28318548202514648f * float(_S32 * k2_2) / 256.0f;
                    r_4[k2_2] = cmul_0(r_4[k2_2], float2(cos(ang_1), sin(ang_1)));

#line 245
                    k2_2 = k2_2 + 1U;

#line 245
                }

#line 252
                uint _S33 = 16U / _S21;
                uint _S34 = max(1U, 1U);
                uint _S35 = tid_0 / _S34;

#line 254
                uint _S36 = tid_0 % _S34;

#line 254
                d_2 = 0U;
                for(;;)
                {

#line 255
                    if(d_2 < 16U)
                    {
                    }
                    else
                    {

#line 255
                        break;
                    }

#line 256
                    uint j_2 = d_2 / _S21;

#line 256
                    uint m_1 = d_2 % _S21;
                    want_2[d_2] = _S31 * 256U + (_S32 * _S33 + j_2) * 16U + m_1;

#line 255
                    d_2 = d_2 + 1U;

#line 255
                }

#line 255
                thread array<uint, int(16)> _S37 = want_2;

#line 255
                exchange_0(&r_4, &_S37, _S20, lgTB_1, kernelContext_3);

#line 233
                break;
            }

#line 233
            break;
        }

#line 233
        break;
    }

#line 263
    innermost_0(&r_4);

#line 276
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 276
    uint b_4 = tid_0;
    for(;;)
    {

#line 277
        if(b_4 < nbins_1)
        {
        }
        else
        {

#line 277
            break;
        }

#line 277
        (*kernelContext_3->stg_0)[b_4] = thrBits_1;

#line 277
        b_4 = b_4 + 256U;

#line 277
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);

    thread array<uint, int(16)> myMag_0;
    thread array<uint, int(16)> myBin_0;

#line 281
    uint i_4 = 0U;
    for(;;)
    {

#line 282
        if(i_4 < 16U)
        {
        }
        else
        {

#line 282
            break;
        }

#line 283
        uint idx_1 = slotToIndex_0(tid_0 * 16U + i_4);
        if(idx_1 >= winStart_1)
        {

#line 284
            live_0 = idx_1 < winEnd_1;

#line 284
        }
        else
        {

#line 284
            live_0 = false;

#line 284
        }



        if(live_0)
        {

#line 288
            n2_0 = (as_type<uint>((r_4[i_4].x * r_4[i_4].x + r_4[i_4].y * r_4[i_4].y)));

#line 288
        }
        else
        {

#line 288
            n2_0 = 0U;

#line 288
        }

#line 288
        myMag_0[i_4] = n2_0;
        uint off_0 = idx_1 - winStart_1;



        if(live_0)
        {

#line 293
            if(binShift_1 >= int(0))
            {

#line 293
                z_1 = off_0 >> uint(binShift_1);

#line 293
            }
            else
            {

#line 293
                uint _S38 = off_0 / binsize_1;

#line 293
                z_1 = _S38;

#line 293
            }

#line 293
        }
        else
        {

#line 293
            z_1 = 0U;

#line 293
        }

#line 293
        myBin_0[i_4] = z_1;

#line 293
        bool _S39;

        if(nbins_1 > 1U)
        {

#line 295
            _S39 = (myMag_0[i_4]) > thrBits_1;

#line 295
        }
        else
        {

#line 295
            _S39 = false;

#line 295
        }

#line 295
        if(_S39)
        {

#line 296
            uint _S40 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[myBin_0[i_4]])), myMag_0[i_4], memory_order_relaxed);

#line 295
        }

#line 282
        i_4 = i_4 + 1U;

#line 282
    }

#line 304
    if(nbins_1 == 1U)
    {

#line 304
        i_4 = 0U;

#line 304
        uint bestBits_0 = thrBits_1;

        for(;;)
        {

#line 306
            if(i_4 < 16U)
            {
            }
            else
            {

#line 306
                break;
            }

#line 306
            uint _S41 = max(bestBits_0, myMag_0[i_4]);

#line 306
            i_4 = i_4 + 1U;

#line 306
            bestBits_0 = _S41;

#line 306
        }
        uint wm_0 = simd_max(bestBits_0);
        bool _S42 = simd_is_first();

#line 308
        if(_S42)
        {

#line 308
            live_0 = wm_0 > thrBits_1;

#line 308
        }
        else
        {

#line 308
            live_0 = false;

#line 308
        }

#line 308
        if(live_0)
        {

#line 308
            uint _S43 = atomic_fetch_max_explicit(((atomic_uint threadgroup*)(&(*kernelContext_3->stg_0)[int(0)])), wm_0, memory_order_relaxed);

#line 308
        }

#line 304
    }

#line 310
    threadgroup_barrier(mem_flags::mem_threadgroup);

#line 310
    i_4 = 0U;

#line 315
    for(;;)
    {

#line 315
        if(i_4 < 16U)
        {
        }
        else
        {

#line 315
            break;
        }

#line 316
        if((myMag_0[i_4]) > thrBits_1)
        {

#line 316
            live_0 = ((*kernelContext_3->stg_0)[myBin_0[i_4]]) == myMag_0[i_4];

#line 316
        }
        else
        {

#line 316
            live_0 = false;

#line 316
        }

#line 316
        if(live_0)
        {

#line 317
            uint o_0 = pair_0 * nbins_1 + myBin_0[i_4];
            *(peakIdx_0+o_0) = int(slotToIndex_0(tid_0 * 16U + i_4));

#line 318
            *(peakVal_0+o_0) = packed_float2(r_4[i_4]) ;

#line 316
        }

#line 315
        i_4 = i_4 + 1U;

#line 315
    }

#line 315
    b_4 = tid_0;

#line 324
    for(;;)
    {

#line 324
        if(b_4 < nbins_1)
        {
        }
        else
        {

#line 324
            break;
        }

#line 325
        if(((*kernelContext_3->stg_0)[b_4]) == thrBits_1)
        {

#line 326
            uint o_1 = pair_0 * nbins_1 + b_4;
            *(peakIdx_0+o_1) = int(-1);

#line 327
            *(peakVal_0+o_1) = packed_float2(float2(0.0f, 0.0f)) ;

#line 325
        }

#line 324
        b_4 = b_4 + 256U;

#line 324
    }

#line 331
    return;
}


#line 421
[[kernel]] void refineListed(uint3 gid_0 [[threadgroup_position_in_grid]], uint3 lid_0 [[thread_position_in_threadgroup]], EntryPointParams_0 constant* entryPointParams_1 [[buffer(0)]], packed_float2 device* entryPointParams_data_1 [[buffer(1)]], packed_float2 device* entryPointParams_tmpl_1 [[buffer(2)]], int device* entryPointParams_peakIdx_1 [[buffer(3)]], packed_float2 device* entryPointParams_peakVal_1 [[buffer(4)]], uint device* entryPointParams_survivors_1 [[buffer(5)]])
{

#line 421
    thread KernelContext_0 kernelContext_4;

#line 421
    (&kernelContext_4)->entryPointParams_0 = entryPointParams_1;

#line 421
    (&kernelContext_4)->entryPointParams_data_0 = entryPointParams_data_1;

#line 421
    (&kernelContext_4)->entryPointParams_tmpl_0 = entryPointParams_tmpl_1;

#line 421
    (&kernelContext_4)->entryPointParams_peakIdx_0 = entryPointParams_peakIdx_1;

#line 421
    (&kernelContext_4)->entryPointParams_peakVal_0 = entryPointParams_peakVal_1;

#line 421
    (&kernelContext_4)->entryPointParams_survivors_0 = entryPointParams_survivors_1;

#line 421
    threadgroup array<uint, int(8192)> stg_1;

#line 421
    (&kernelContext_4)->stg_0 = &stg_1;

#line 421
    filterPair_0(entryPointParams_survivors_1[gid_0.x], lid_0.x, entryPointParams_data_1, entryPointParams_tmpl_1, entryPointParams_peakIdx_1, entryPointParams_peakVal_1, entryPointParams_1->ntmpl_0, entryPointParams_1->winStart_0, entryPointParams_1->winEnd_0, entryPointParams_1->binsize_0, entryPointParams_1->binShift_0, entryPointParams_1->nbins_0, entryPointParams_1->thrBits_0, &kernelContext_4);

#line 433
    return;
}

