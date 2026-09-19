/* peakfft: L1-resident 1024-point AVX-512 kernel.
 *
 * Four-step 32x32 on split (SoA) complex data.  Both 32-point stages are
 * generated radix-8 x radix-4 Stockham codelets (2 passes, not radix-2's 5),
 * fully unrolled with compile-time twiddles; trivial twiddles (+-1, +-i) cost
 * no multiplies.  The 32x32 corner turn is a canonical 16x16 register transpose.
 */
#include <stddef.h>
#include <string.h>
#include <immintrin.h>
#include "internal.h"
#include "transpose16.h"
#include "codelets.h"

/* AoS complex -> SoA, vectorised */
void pf_deint_c(const float*in,float*re,float*im,size_t N,int conj){
  const __m512i ev=_mm512_setr_epi32(0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30);
  const __m512i od=_mm512_setr_epi32(1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31);
  const __m512 sg=conj?_mm512_castsi512_ps(_mm512_set1_epi32((int)0x80000000)):_mm512_setzero_ps();
  for(size_t i=0;i<N;i+=16){
    __m512 a=_mm512_loadu_ps(in+2*i), b=_mm512_loadu_ps(in+2*i+16);
    _mm512_store_ps(re+i,_mm512_permutex2var_ps(a,ev,b));
    _mm512_store_ps(im+i,_mm512_xor_ps(_mm512_permutex2var_ps(a,od,b),sg));
  }
}
void pf_inter_c(const float*re,const float*im,float*out,size_t N,int conj){
  const __m512i lo=_mm512_setr_epi32(0,16,1,17,2,18,3,19,4,20,5,21,6,22,7,23);
  const __m512i hi=_mm512_setr_epi32(8,24,9,25,10,26,11,27,12,28,13,29,14,30,15,31);
  const __m512 sg=conj?_mm512_castsi512_ps(_mm512_set1_epi32((int)0x80000000)):_mm512_setzero_ps();
  for(size_t i=0;i<N;i+=16){
    __m512 r=_mm512_load_ps(re+i), m=_mm512_xor_ps(_mm512_load_ps(im+i),sg);
    _mm512_storeu_ps(out+2*i,   _mm512_permutex2var_ps(r,lo,m));
    _mm512_storeu_ps(out+2*i+16,_mm512_permutex2var_ps(r,hi,m));
  }
}
void pf_deint(const float*in,float*re,float*im,size_t N){
  const __m512i ev=_mm512_setr_epi32(0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30);
  const __m512i od=_mm512_setr_epi32(1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31);
  for(size_t i=0;i<N;i+=16){
    __m512 a=_mm512_loadu_ps(in+2*i), b=_mm512_loadu_ps(in+2*i+16);
    _mm512_store_ps(re+i,_mm512_permutex2var_ps(a,ev,b));
    _mm512_store_ps(im+i,_mm512_permutex2var_ps(a,od,b));
  }
}
void pf_inter(const float*re,const float*im,float*out,size_t N){
  const __m512i lo=_mm512_setr_epi32(0,16,1,17,2,18,3,19,4,20,5,21,6,22,7,23);
  const __m512i hi=_mm512_setr_epi32(8,24,9,25,10,26,11,27,12,28,13,29,14,30,15,31);
  for(size_t i=0;i<N;i+=16){
    __m512 r=_mm512_load_ps(re+i), m=_mm512_load_ps(im+i);
    _mm512_storeu_ps(out+2*i,   _mm512_permutex2var_ps(r,lo,m));
    _mm512_storeu_ps(out+2*i+16,_mm512_permutex2var_ps(r,hi,m));
  }
}


/* in-place 1024-pt FFT on SoA arrays re[1024], im[1024] (64B aligned).
   n = n2*32+n1 (n1 fast).  Output natural order k = k1*32+k2. */
__attribute__((always_inline))
static inline void fft1024_core(float *re,float *im,
                                const __m512 (*t4r)[32],const __m512 (*t4i)[32],
                                __m512 *vmaxout,const int want_mag){
  __m512 vmax=_mm512_setzero_ps();
  __m512 A[32],B[32],C[32],D[32];
  __m512 Vr[2][32],Vi[2][32];
  /* ---- inner: 32 DFTs of size 32 over n2 (stride 32); lanes = n1 ---- */
  for(int c=0;c<2;c++){
    for(int n2=0;n2<32;n2++){ A[n2]=_mm512_loadu_ps(re+n2*32+16*c); B[n2]=_mm512_loadu_ps(im+n2*32+16*c); }
    int f=fft32_84(A,B,C,D,1);
    __m512*Rr = f?C:A, *Ri = f?D:B;
    for(int k2=0;k2<32;k2++){
      __m512 xr=Rr[k2],xi=Ri[k2], tr=t4r[c][k2], ti=t4i[c][k2];
      Vr[c][k2]=_mm512_fmsub_ps(xr,tr,_mm512_mul_ps(xi,ti));
      Vi[c][k2]=_mm512_fmadd_ps(xr,ti,_mm512_mul_ps(xi,tr));
    }
  }
  /* ---- transpose 32x32: [n1][k2] -> [k2 lane][n1 elem] ---- */
  __m512 Tr[32],Ti[32];  /* element = n1 (0..31), lanes = k2 block d */
  for(int d=0;d<2;d++){
    for(int c=0;c<2;c++){
      t16(&Vr[c][16*d], &Tr[16*c]);
      t16(&Vi[c][16*d], &Ti[16*c]);
    }
    /* ---- outer: 32-point DFT over n1 ; lanes = k2 ---- */
    int f=fft32_84(Tr,Ti,A,B,1);
    __m512*Rr=f?A:Tr, *Ri=f?B:Ti;
    /* output k = k1*32 + k2 ; element=k1, lane=k2 (+16d) */
    for(int k1=0;k1<32;k1++){
      __m512 r=Rr[k1], i=Ri[k1];
      _mm512_storeu_ps(re+k1*32+16*d,r);
      _mm512_storeu_ps(im+k1*32+16*d,i);
      if(want_mag){
        /* The running per-lane maximum of |X|^2 is nearly free here - the values are
           already in registers.  It gives pf_topk a tight scan threshold without a
           pass of its own.  |X|^2 itself is deliberately NOT stored: the final stage
           is store-port bound, and writing it back costs more than it saves. */
        vmax=_mm512_max_ps(vmax,_mm512_fmadd_ps(r,r,_mm512_mul_ps(i,i)));
      }
    }
  }
  if(want_mag) *vmaxout=vmax;
}

void pf_fft1024_soa(float *re,float *im,const __m512 (*t4r)[32],const __m512 (*t4i)[32]){
  fft1024_core(re,im,t4r,t4i,NULL,0);
}
void pf_fft1024_soa_mag(float *re,float *im,const __m512 (*t4r)[32],const __m512 (*t4i)[32],
                        __m512 *vmax){
  fft1024_core(re,im,t4r,t4i,vmax,1);
}

