#ifndef PF_T16_H
#define PF_T16_H
#include <immintrin.h>
#define CPD(x) _mm512_castps_pd(x)
#define CPS(x) _mm512_castpd_ps(x)
static inline void t16(const __m512*i,__m512*o){
  __m512 t[16],u[16];
  for(int k=0;k<8;k++){ t[2*k]=_mm512_unpacklo_ps(i[2*k],i[2*k+1]); t[2*k+1]=_mm512_unpackhi_ps(i[2*k],i[2*k+1]); }
  for(int g=0;g<4;g++){
    u[4*g+0]=CPS(_mm512_unpacklo_pd(CPD(t[4*g+0]),CPD(t[4*g+2])));
    u[4*g+1]=CPS(_mm512_unpackhi_pd(CPD(t[4*g+0]),CPD(t[4*g+2])));
    u[4*g+2]=CPS(_mm512_unpacklo_pd(CPD(t[4*g+1]),CPD(t[4*g+3])));
    u[4*g+3]=CPS(_mm512_unpackhi_pd(CPD(t[4*g+1]),CPD(t[4*g+3])));
  }
  for(int k=0;k<4;k++){
    t[k]   =_mm512_shuffle_f32x4(u[k],   u[k+4], 0x88);
    t[k+4] =_mm512_shuffle_f32x4(u[k],   u[k+4], 0xdd);
    t[k+8] =_mm512_shuffle_f32x4(u[k+8], u[k+12],0x88);
    t[k+12]=_mm512_shuffle_f32x4(u[k+8], u[k+12],0xdd);
  }
  for(int k=0;k<8;k++){
    o[k]  =_mm512_shuffle_f32x4(t[k],t[k+8],0x88);
    o[k+8]=_mm512_shuffle_f32x4(t[k],t[k+8],0xdd);
  }
}

#endif
