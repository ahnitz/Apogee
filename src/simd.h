/* Width abstraction so one source compiles to both AVX-512 (W=16) and AVX2 (W=8).
   Only the operations matchedfilter's width-generic back end actually needs. */
#ifndef AP_SIMD_H
#define AP_SIMD_H
#include <stdint.h>

/* `restrict` is C99 and not a C++ keyword.  The generated codelets use it
   heavily, so map it rather than regenerate them differently per language. */
#ifdef __cplusplus
#define restrict __restrict
#endif

#ifndef AP_W
#error "define AP_W to 16 (AVX-512) or 8 (AVX2)"
#endif

/* Three SIMD layers behind one macro surface.  AP_HIGHWAY uses Google
   Highway (C++), AP_PORTABLE uses GCC/Clang vector extensions, and the
   default is the hand-written x86 intrinsics.  codelets.h and balanced.c
   see only the V_* macros and are identical across all three. */
#if defined(AP_HIGHWAY)
#include "simd_hwy.h"
#elif defined(AP_PORTABLE)
#include "simd_portable.h"
#else
#include <immintrin.h>

#if AP_W == 16
typedef __m512 vf;
typedef __m512i vi;          /* integer view, for the peak scan's index vector */
#define VI_SET1(x)      _mm512_set1_epi32(x)
#define V_ZERO()        _mm512_setzero_ps()
#define VI_STOREU(p,v)   _mm512_storeu_si512((void*)(p),v)
#define V_SET1(x)       _mm512_set1_ps(x)
#define V_LOADU(p)      _mm512_loadu_ps(p)
#define V_STOREU(p,v)   _mm512_storeu_ps(p,v)
#define V_ADD(a,b)      _mm512_add_ps(a,b)
#define V_SUB(a,b)      _mm512_sub_ps(a,b)
#define V_MUL(a,b)      _mm512_mul_ps(a,b)
#define V_FMADD(a,b,c)  _mm512_fmadd_ps(a,b,c)
#define V_FMSUB(a,b,c)  _mm512_fmsub_ps(a,b,c)
#define V_FNMADD(a,b,c) _mm512_fnmadd_ps(a,b,c)   /* -(a*b)+c */
#define V_FNMSUB(a,b,c) _mm512_fnmsub_ps(a,b,c)   /* -(a*b)-c */
#define V_XOR(a,b)      _mm512_xor_ps(a,b)
#define V_SIGNMASK()    _mm512_castsi512_ps(_mm512_set1_epi32((int)0x80000000))
/* Opaque lane mask.  The peak scan compares and then selects, and going
   through a bitmask in between is free here but not everywhere, so the type
   stays abstract and only becomes bits where bits are actually wanted. */
typedef __mmask16 vm;
#define V_CMP_GT(a,b)        _mm512_cmp_ps_mask(a,b,_CMP_GT_OQ)
#define V_MASK_ANY(m)        ((m)!=0)
#define V_MASK_FROM_BITS(u)  ((__mmask16)(u))
#define V_SEL(m,a,b)         _mm512_mask_blend_ps(m,a,b)
#define VI_SEL(m,a,b)        _mm512_mask_blend_epi32(m,a,b)

#elif AP_W == 8
typedef __m256 vf;
typedef __m256i vi;
#define VI_SET1(x)      _mm256_set1_epi32(x)
#define V_ZERO()        _mm256_setzero_ps()
/* AVX2 has no mask registers; V_GT_MASK hands back a movemask bitfield, so turn
   it back into a lane mask for the blend.  Eight lanes, so a 256-bit table would
   be 8 KiB - cheaper to splat the bits and test them. */
static inline __m256 v_maskof(unsigned m){
  const __m256i bit=_mm256_setr_epi32(1,2,4,8,16,32,64,128);
  __m256i v=_mm256_and_si256(_mm256_set1_epi32((int)m),bit);
  return _mm256_castsi256_ps(_mm256_cmpeq_epi32(v,bit));
}
#define VI_STOREU(p,v)   _mm256_storeu_si256((__m256i*)(p),v)
#define V_SET1(x)       _mm256_set1_ps(x)
#define V_LOADU(p)      _mm256_loadu_ps(p)
#define V_STOREU(p,v)   _mm256_storeu_ps(p,v)
#define V_ADD(a,b)      _mm256_add_ps(a,b)
#define V_SUB(a,b)      _mm256_sub_ps(a,b)
#define V_MUL(a,b)      _mm256_mul_ps(a,b)
#define V_FMADD(a,b,c)  _mm256_fmadd_ps(a,b,c)
#define V_FMSUB(a,b,c)  _mm256_fmsub_ps(a,b,c)
#define V_FNMADD(a,b,c) _mm256_fnmadd_ps(a,b,c)
#define V_FNMSUB(a,b,c) _mm256_fnmsub_ps(a,b,c)
#define V_XOR(a,b)      _mm256_xor_ps(a,b)
#define V_SIGNMASK()    _mm256_castsi256_ps(_mm256_set1_epi32((int)0x80000000))
typedef __m256 vm;
#define V_CMP_GT(a,b)        _mm256_cmp_ps(a,b,_CMP_GT_OQ)
#define V_MASK_ANY(m)        (_mm256_movemask_ps(m)!=0)
#define V_MASK_FROM_BITS(u)  v_maskof(u)
#define V_SEL(m,a,b)         _mm256_blendv_ps(a,b,m)
#define VI_SEL(m,a,b)        _mm256_castps_si256(_mm256_blendv_ps( \
                               _mm256_castsi256_ps(a),_mm256_castsi256_ps(b),m))
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

static inline float v_reduce_max(vf v){
  float t[AP_W]; V_STOREU(t,v);
  float m=t[0];
  for(int i=1;i<AP_W;i++) if(t[i]>m) m=t[i];
  return m;
}
#endif /* SIMD layer */
#endif
