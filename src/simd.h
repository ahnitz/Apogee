/* Width abstraction so one source compiles to both AVX-512 (W=16) and AVX2 (W=8).
   Only the operations matchedfilter's width-generic back end actually needs. */
#ifndef AP_SIMD_H
#define AP_SIMD_H
#include <immintrin.h>
#include <stdint.h>

#ifndef AP_W
#error "define AP_W to 16 (AVX-512) or 8 (AVX2)"
#endif

#if AP_W == 16
typedef __m512 vf;
#define V_ZERO()        _mm512_setzero_ps()
/* select by mask: lane set -> take b, clear -> keep a */
#define V_BLENDM(m,a,b)  _mm512_mask_blend_ps((__mmask16)(m),a,b)
#define VI_BLENDM(m,a,b) _mm512_mask_blend_epi32((__mmask16)(m),a,b)
#define VI_STOREU(p,v)   _mm512_storeu_si512((void*)(p),v)
#define V_SET1(x)       _mm512_set1_ps(x)
#define V_LOAD(p)       _mm512_load_ps(p)
#define V_LOADU(p)      _mm512_loadu_ps(p)
#define V_STORE(p,v)    _mm512_store_ps(p,v)
#define V_STOREU(p,v)   _mm512_storeu_ps(p,v)
#define V_ADD(a,b)      _mm512_add_ps(a,b)
#define V_SUB(a,b)      _mm512_sub_ps(a,b)
#define V_MUL(a,b)      _mm512_mul_ps(a,b)
#define V_FMADD(a,b,c)  _mm512_fmadd_ps(a,b,c)
#define V_FMSUB(a,b,c)  _mm512_fmsub_ps(a,b,c)
#define V_FNMADD(a,b,c) _mm512_fnmadd_ps(a,b,c)   /* -(a*b)+c */
#define V_FNMSUB(a,b,c) _mm512_fnmsub_ps(a,b,c)   /* -(a*b)-c */
#define V_MAX(a,b)      _mm512_max_ps(a,b)
#define V_XOR(a,b)      _mm512_xor_ps(a,b)
#define V_SIGNMASK()    _mm512_castsi512_ps(_mm512_set1_epi32((int)0x80000000))
#define V_ABS(a)        _mm512_abs_ps(a)
/* greater-than as a plain bitmask, one bit per lane */
#define V_GT_MASK(a,b)  ((unsigned)_mm512_cmp_ps_mask(a,b,_CMP_GT_OQ))

#elif AP_W == 8
typedef __m256 vf;
#define V_ZERO()        _mm256_setzero_ps()
/* AVX2 has no mask registers; V_GT_MASK hands back a movemask bitfield, so turn
   it back into a lane mask for the blend.  Eight lanes, so a 256-bit table would
   be 8 KiB - cheaper to splat the bits and test them. */
static inline __m256 v_maskof(unsigned m){
  const __m256i bit=_mm256_setr_epi32(1,2,4,8,16,32,64,128);
  __m256i v=_mm256_and_si256(_mm256_set1_epi32((int)m),bit);
  return _mm256_castsi256_ps(_mm256_cmpeq_epi32(v,bit));
}
#define V_BLENDM(m,a,b)  _mm256_blendv_ps(a,b,v_maskof(m))
#define VI_BLENDM(m,a,b) _mm256_castps_si256(_mm256_blendv_ps( \
                           _mm256_castsi256_ps(a),_mm256_castsi256_ps(b),v_maskof(m)))
#define VI_STOREU(p,v)   _mm256_storeu_si256((__m256i*)(p),v)
#define V_SET1(x)       _mm256_set1_ps(x)
#define V_LOAD(p)       _mm256_load_ps(p)
#define V_LOADU(p)      _mm256_loadu_ps(p)
#define V_STORE(p,v)    _mm256_store_ps(p,v)
#define V_STOREU(p,v)   _mm256_storeu_ps(p,v)
#define V_ADD(a,b)      _mm256_add_ps(a,b)
#define V_SUB(a,b)      _mm256_sub_ps(a,b)
#define V_MUL(a,b)      _mm256_mul_ps(a,b)
#define V_FMADD(a,b,c)  _mm256_fmadd_ps(a,b,c)
#define V_FMSUB(a,b,c)  _mm256_fmsub_ps(a,b,c)
#define V_FNMADD(a,b,c) _mm256_fnmadd_ps(a,b,c)
#define V_FNMSUB(a,b,c) _mm256_fnmsub_ps(a,b,c)
#define V_MAX(a,b)      _mm256_max_ps(a,b)
#define V_XOR(a,b)      _mm256_xor_ps(a,b)
#define V_SIGNMASK()    _mm256_castsi256_ps(_mm256_set1_epi32((int)0x80000000))
#define V_ABS(a)        _mm256_andnot_ps(_mm256_castsi256_ps(_mm256_set1_epi32((int)0x80000000)),a)
#define V_GT_MASK(a,b)  ((unsigned)_mm256_movemask_ps(_mm256_cmp_ps(a,b,_CMP_GT_OQ)))
#else
#error "AP_W must be 16 or 8"
#endif

/* ---- W x W register transpose ---- */
#if AP_W == 16
#include "transpose16.h"
#define V_TRANSPOSE(in,out) t16((in),(out))
#else
static inline void t8(const __m256 *i, __m256 *o){
  __m256 t[8],u[8];
  t[0]=_mm256_unpacklo_ps(i[0],i[1]); t[1]=_mm256_unpackhi_ps(i[0],i[1]);
  t[2]=_mm256_unpacklo_ps(i[2],i[3]); t[3]=_mm256_unpackhi_ps(i[2],i[3]);
  t[4]=_mm256_unpacklo_ps(i[4],i[5]); t[5]=_mm256_unpackhi_ps(i[4],i[5]);
  t[6]=_mm256_unpacklo_ps(i[6],i[7]); t[7]=_mm256_unpackhi_ps(i[6],i[7]);
  u[0]=_mm256_shuffle_ps(t[0],t[2],0x44); u[1]=_mm256_shuffle_ps(t[0],t[2],0xEE);
  u[2]=_mm256_shuffle_ps(t[1],t[3],0x44); u[3]=_mm256_shuffle_ps(t[1],t[3],0xEE);
  u[4]=_mm256_shuffle_ps(t[4],t[6],0x44); u[5]=_mm256_shuffle_ps(t[4],t[6],0xEE);
  u[6]=_mm256_shuffle_ps(t[5],t[7],0x44); u[7]=_mm256_shuffle_ps(t[5],t[7],0xEE);
  o[0]=_mm256_permute2f128_ps(u[0],u[4],0x20); o[1]=_mm256_permute2f128_ps(u[1],u[5],0x20);
  o[2]=_mm256_permute2f128_ps(u[2],u[6],0x20); o[3]=_mm256_permute2f128_ps(u[3],u[7],0x20);
  o[4]=_mm256_permute2f128_ps(u[0],u[4],0x31); o[5]=_mm256_permute2f128_ps(u[1],u[5],0x31);
  o[6]=_mm256_permute2f128_ps(u[2],u[6],0x31); o[7]=_mm256_permute2f128_ps(u[3],u[7],0x31);
}
#define V_TRANSPOSE(in,out) t8((in),(out))
#endif

/* ---- interleaved complex <-> split, one vector's worth ---- */
#if AP_W == 16
static inline void v_deint(const float *p, vf *re, vf *im){
  const __m512i ev=_mm512_setr_epi32(0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30);
  const __m512i od=_mm512_setr_epi32(1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31);
  __m512 a=_mm512_loadu_ps(p), b=_mm512_loadu_ps(p+16);
  *re=_mm512_permutex2var_ps(a,ev,b); *im=_mm512_permutex2var_ps(a,od,b);
}
static inline void v_inter(float *p, vf re, vf im){
  const __m512i lo=_mm512_setr_epi32(0,16,1,17,2,18,3,19,4,20,5,21,6,22,7,23);
  const __m512i hi=_mm512_setr_epi32(8,24,9,25,10,26,11,27,12,28,13,29,14,30,15,31);
  _mm512_storeu_ps(p,   _mm512_permutex2var_ps(re,lo,im));
  _mm512_storeu_ps(p+16,_mm512_permutex2var_ps(re,hi,im));
}
#else
static inline void v_deint(const float *p, vf *re, vf *im){
  const __m256i ix=_mm256_setr_epi32(0,1,4,5,2,3,6,7);
  __m256 a=_mm256_loadu_ps(p), b=_mm256_loadu_ps(p+8);
  *re=_mm256_permutevar8x32_ps(_mm256_shuffle_ps(a,b,0x88),ix);
  *im=_mm256_permutevar8x32_ps(_mm256_shuffle_ps(a,b,0xDD),ix);
}
static inline void v_inter(float *p, vf re, vf im){
  __m256 lo=_mm256_unpacklo_ps(re,im), hi=_mm256_unpackhi_ps(re,im);
  _mm256_storeu_ps(p,  _mm256_permute2f128_ps(lo,hi,0x20));
  _mm256_storeu_ps(p+8,_mm256_permute2f128_ps(lo,hi,0x31));
}
#endif

/* ---- int16 Q15 arithmetic (AVX-512 only for now) ----
   32 lanes per register.  VQ15_MUL is vpmulhrsw: (a*b + 0x4000) >> 15, i.e. a Q15
   multiply whose built-in >>15 means twiddles never grow the data. */
#if AP_W == 16
typedef __m512i vq15;
#define VQ15_SET1(x)   _mm512_set1_epi16(x)
#define VQ15_ADD(a,b)  _mm512_add_epi16(a,b)
#define VQ15_SUB(a,b)  _mm512_sub_epi16(a,b)
#define VQ15_NEG(a)    _mm512_sub_epi16(_mm512_setzero_si512(),a)
#define VQ15_SRA(a,n)  ((n)?_mm512_srai_epi16(a,n):(a))
#define VQ15_MUL(a,b) _mm512_mulhrs_epi16(a,b)
#else
typedef __m256i vq15;
#define VQ15_SET1(x)   _mm256_set1_epi16(x)
#define VQ15_ADD(a,b)  _mm256_add_epi16(a,b)
#define VQ15_SUB(a,b)  _mm256_sub_epi16(a,b)
#define VQ15_NEG(a)    _mm256_sub_epi16(_mm256_setzero_si256(),a)
#define VQ15_SRA(a,n)  ((n)?_mm256_srai_epi16(a,n):(a))
#define VQ15_MUL(a,b) _mm256_mulhrs_epi16(a,b)
#endif

/* ---- fixed-point conversion for the quantised intermediate ----
   The screening pass only needs ~1e-2 relative accuracy, so the intermediate is
   kept as 24-bit block floating point: a 16-bit plane that screening reads, and an
   8-bit residual read only for the few columns holding a winner. */
#if AP_W == 16
typedef __m512i vi;
typedef __m256i vi16;   /* W packed int16 */
typedef __m128i vi8;    /* W packed int8  */
#define VI_CVT(x)        _mm512_cvtps_epi32(x)
#define VI_CVTF(x)       _mm512_cvtepi32_ps(x)
#define VI_MIN(a,b)      _mm512_min_epi32(a,b)
#define VI_MAX(a,b)      _mm512_max_epi32(a,b)
#define VI_SET1(x)       _mm512_set1_epi32(x)
#define VI_SRAI(a,n)     _mm512_srai_epi32(a,n)
#define VI_SLLI(a,n)     _mm512_slli_epi32(a,n)
#define VI_AND(a,b)      _mm512_and_epi32(a,b)
#define VI_OR(a,b)       _mm512_or_epi32(a,b)
#define VI_PACK16(a)     _mm512_cvtepi32_epi16(a)
#define VI_PACK8(a)      _mm512_cvtepi32_epi8(a)
#define VI_LOAD16(p)     _mm256_loadu_si256((const __m256i*)(p))
#define VI_LOAD8(p)      _mm_loadu_si128((const __m128i*)(p))
#define VI_STORE16(p,v)  _mm256_storeu_si256((__m256i*)(p),v)
#define VI_STORE8(p,v)   _mm_storeu_si128((__m128i*)(p),v)
#define VI_UNPACK16(v)   _mm512_cvtepi16_epi32(v)
#define VI_UNPACKU8(v)   _mm512_cvtepu8_epi32(v)
#else
typedef __m256i vi;
typedef __m128i vi16;
typedef __m128i vi8;
#define VI_CVT(x)        _mm256_cvtps_epi32(x)
#define VI_CVTF(x)       _mm256_cvtepi32_ps(x)
#define VI_MIN(a,b)      _mm256_min_epi32(a,b)
#define VI_MAX(a,b)      _mm256_max_epi32(a,b)
#define VI_SET1(x)       _mm256_set1_epi32(x)
#define VI_SRAI(a,n)     _mm256_srai_epi32(a,n)
#define VI_SLLI(a,n)     _mm256_slli_epi32(a,n)
#define VI_AND(a,b)      _mm256_and_si256(a,b)
#define VI_OR(a,b)       _mm256_or_si256(a,b)
/* 8 x int32 -> 8 x int16 in one 128-bit lane (packs works per 128-bit half,
   so the halves must be re-joined with a 64-bit permute) */
static inline __m128i vi_pack16(__m256i a){
  __m256i p=_mm256_packs_epi32(a,a);
  return _mm256_castsi256_si128(_mm256_permute4x64_epi64(p,0xD8));
}
/* Take the LOW byte of each int32, by truncation.  packs_* would saturate, which
   silently clamps residual bytes >= 128 to 127 and destroys the low 8 bits. */
static inline __m128i vi_pack8(__m256i a){
  const __m256i sh=_mm256_setr_epi8(0,4,8,12,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,
                                    0,4,8,12,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1,-1);
  __m256i t=_mm256_shuffle_epi8(a,sh);
  __m128i lo=_mm256_castsi256_si128(t), hi=_mm256_extracti128_si256(t,1);
  return _mm_unpacklo_epi32(lo,hi);
}
#define VI_PACK16(a)     vi_pack16(a)
#define VI_PACK8(a)      vi_pack8(a)
#define VI_LOAD16(p)     _mm_loadu_si128((const __m128i*)(p))
#define VI_LOAD8(p)      _mm_loadl_epi64((const __m128i*)(p))
#define VI_STORE16(p,v)  _mm_storeu_si128((__m128i*)(p),v)
#define VI_STORE8(p,v)   _mm_storel_epi64((__m128i*)(p),v)
#define VI_UNPACK16(v)   _mm256_cvtepi16_epi32(v)
#define VI_UNPACKU8(v)   _mm256_cvtepu8_epi32(v)
#endif

static inline float v_reduce_max(vf v){
  float t[AP_W]; V_STOREU(t,v);
  float m=t[0];
  for(int i=1;i<AP_W;i++) if(t[i]>m) m=t[i];
  return m;
}
#endif
