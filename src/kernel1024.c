/* matchedfilter: L1-resident 1024-point AVX-512 kernel.
 *
 * Four-step 32x32 on split (SoA) complex data.  Both 32-point stages are
 * generated radix-8 x radix-4 Stockham codelets (2 passes, not radix-2's 5),
 * fully unrolled with compile-time twiddles; trivial twiddles (+-1, +-i) cost
 * no multiplies.  The 32x32 corner turn is a canonical 16x16 register transpose.
 */
#include <stddef.h>
#include <string.h>
#include <immintrin.h>
#include <math.h>
#include "internal.h"
#include "transpose16.h"
#include "codelets.h"

/* AoS complex -> SoA, vectorised */
void ap_deint_c(const float*in,float*re,float*im,size_t N,int conj){
  const __m512i ev=_mm512_setr_epi32(0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30);
  const __m512i od=_mm512_setr_epi32(1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31);
  const __m512 sg=conj?_mm512_castsi512_ps(_mm512_set1_epi32((int)0x80000000)):_mm512_setzero_ps();
  for(size_t i=0;i<N;i+=16){
    __m512 a=_mm512_loadu_ps(in+2*i), b=_mm512_loadu_ps(in+2*i+16);
    _mm512_store_ps(re+i,_mm512_permutex2var_ps(a,ev,b));
    _mm512_store_ps(im+i,_mm512_xor_ps(_mm512_permutex2var_ps(a,od,b),sg));
  }
}
void ap_inter_c(const float*re,const float*im,float*out,size_t N,int conj){
  const __m512i lo=_mm512_setr_epi32(0,16,1,17,2,18,3,19,4,20,5,21,6,22,7,23);
  const __m512i hi=_mm512_setr_epi32(8,24,9,25,10,26,11,27,12,28,13,29,14,30,15,31);
  const __m512 sg=conj?_mm512_castsi512_ps(_mm512_set1_epi32((int)0x80000000)):_mm512_setzero_ps();
  for(size_t i=0;i<N;i+=16){
    __m512 r=_mm512_load_ps(re+i), m=_mm512_xor_ps(_mm512_load_ps(im+i),sg);
    _mm512_storeu_ps(out+2*i,   _mm512_permutex2var_ps(r,lo,m));
    _mm512_storeu_ps(out+2*i+16,_mm512_permutex2var_ps(r,hi,m));
  }
}
void ap_deint(const float*in,float*re,float*im,size_t N){
  const __m512i ev=_mm512_setr_epi32(0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30);
  const __m512i od=_mm512_setr_epi32(1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31);
  for(size_t i=0;i<N;i+=16){
    __m512 a=_mm512_loadu_ps(in+2*i), b=_mm512_loadu_ps(in+2*i+16);
    _mm512_store_ps(re+i,_mm512_permutex2var_ps(a,ev,b));
    _mm512_store_ps(im+i,_mm512_permutex2var_ps(a,od,b));
  }
}
void ap_inter(const float*re,const float*im,float*out,size_t N){
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
           already in registers.  It gives ap_topk a tight scan threshold without a
           pass of its own.  |X|^2 itself is deliberately NOT stored: the final stage
           is store-port bound, and writing it back costs more than it saves. */
        vmax=_mm512_max_ps(vmax,_mm512_fmadd_ps(r,r,_mm512_mul_ps(i,i)));
      }
    }
  }
  if(want_mag) *vmaxout=vmax;
}

void ap_fft1024_soa(float *re,float *im,const __m512 (*t4r)[32],const __m512 (*t4i)[32]){
  fft1024_core(re,im,t4r,t4i,NULL,0);
}
void ap_fft1024_soa_mag(float *re,float *im,const __m512 (*t4r)[32],const __m512 (*t4i)[32],
                        __m512 *vmax){
  fft1024_core(re,im,t4r,t4i,vmax,1);
}

/* Transform with the peak search fused into its final stage.
 *
 * The scan normally costs a second pass: store 8 KiB of re/im, reload it, square,
 * compare.  Given a detection floor up front we can do the compare while the
 * outputs are still in registers, which removes the pass and most of the stores -
 * only blocks that produce a candidate are written back at all.
 *
 * This is the one place the relaxed spec buys something a general FFT cannot have:
 * a full FFT must materialise every output, and we do not.
 *
 * thr2 is the squared floor.  The heap raises it as it fills, so the compare gets
 * tighter as the scan proceeds.  re/im are still updated for candidate blocks
 * because the caller refines and reports exact values from them.
 */
int ap_fft1024_topk(const float *re,const float *im,
                    const __m512 (*t4r)[32],const __m512 (*t4i)[32],
                    float thr2,long ws,long we,int K,ap_cand *T){
  __m512 A[32],B[32],C[32],D[32];
  __m512 Vr[2][32],Vi[2][32];
  /* Folding the AoS->SoA split into this loop was tried and is slightly slower:
     it turns ap_deint_c's streaming pass into strided 128-of-256-byte reads and
     puts two more permutes on the shuffle port the butterflies are already using.
     0.391 us against 0.381.  Keep the split as its own pass. */
  for(int c=0;c<2;c++){
    for(int n2=0;n2<32;n2++){
      A[n2]=_mm512_loadu_ps(re+n2*32+16*c); B[n2]=_mm512_loadu_ps(im+n2*32+16*c);
    }
    int f=fft32_84(A,B,C,D,1);
    __m512*Rr = f?C:A, *Ri = f?D:B;
    for(int k2=0;k2<32;k2++){
      __m512 xr=Rr[k2],xi=Ri[k2], tr=t4r[c][k2], ti=t4i[c][k2];
      Vr[c][k2]=_mm512_fmsub_ps(xr,tr,_mm512_mul_ps(xi,ti));
      Vi[c][k2]=_mm512_fmadd_ps(xr,ti,_mm512_mul_ps(xi,tr));
    }
  }
  __m512 Tr[32],Ti[32];
  int n=0;
  float thr=thr2;
  __m512 vthr=_mm512_set1_ps(thr);
  const int full = (ws<=0 && we>=1024);
  for(int d=0;d<2;d++){
    for(int c=0;c<2;c++){ t16(&Vr[c][16*d],&Tr[16*c]); t16(&Vi[c][16*d],&Ti[16*c]); }
    int f=fft32_84(Tr,Ti,A,B,1);
    __m512*Rr=f?A:Tr, *Ri=f?B:Ti;
    for(int k1=0;k1<32;k1++){
      __m512 r=Rr[k1], i=Ri[k1];
      long k0=k1*32+16*d;
      __mmask16 inw=0xFFFF;
      if(!full){
        if(k0+16<=ws || k0>=we) continue;
        if(k0<ws || k0+16>we){ inw=0;
          for(int l=0;l<16;l++){ long k=k0+l; if(k>=ws&&k<we) inw|=(__mmask16)(1u<<l); } }
      }
      __m512 m2=_mm512_fmadd_ps(r,r,_mm512_mul_ps(i,i));
      __mmask16 msk=_mm512_cmp_ps_mask(m2,vthr,_CMP_GT_OQ)&inw;
      if(__builtin_expect(msk!=0,0)){
        /* the outputs themselves are never stored - only the few lanes that
           survive the floor are ever spilled, and only to the stack */
        float bm[16],br[16],bi[16];
        _mm512_storeu_ps(bm,m2); _mm512_storeu_ps(br,r); _mm512_storeu_ps(bi,i);
        while(msk){
          int l=__builtin_ctz((unsigned)msk); msk&=(__mmask16)(msk-1);
          if(bm[l]<=thr) continue;
          ap_push(T,K,&n,bm[l],(int)(k0+l),br[l],bi[l]);
          if(n==K){ thr=T[0].mag2; vthr=_mm512_set1_ps(thr); }
        }
      }
    }
  }
  return n;
}




/* Binned maximum fused into the transform's final stage.
 *
 * Same idea as ap_fft1024_topk - the outputs are compared while still in
 * registers and never stored - but the survivor test is a per-bin running max
 * instead of a heap.  That makes it branchless: no candidate pool, no pushes,
 * no final sort, and a cost that does not depend on the data.
 *
 * Accumulators stay vectors through the whole scan; each bin is reduced once at
 * the end.  The winner's re/im ride in their own accumulators so the exact
 * complex value survives without materialising the spectrum.
 */
static int fft1024_binmax_many(__m512 Vr[2][32],__m512 Vi[2][32],
                               __m512 *A,__m512 *B,__m512 *Tr,__m512 *Ti,
                               long nb,size_t binsize,float thr,ap_peak *out,
                               int conj,long ws,long we,int full,__m512 NEG);

int ap_fft1024_binmax(float *re,float *im,
                      const __m512 (*t4r)[32],const __m512 (*t4i)[32],
                      size_t binsize,float thr,ap_peak *out,int conj,
                      long ws,long we){
  __m512 A[32],B[32],C[32],D[32];
  __m512 Vr[2][32],Vi[2][32];
  for(int c=0;c<2;c++){
    for(int n2=0;n2<32;n2++){
      A[n2]=_mm512_loadu_ps(re+n2*32+16*c); B[n2]=_mm512_loadu_ps(im+n2*32+16*c);
    }
    int f=fft32_84(A,B,C,D,1);
    __m512*Rr = f?C:A, *Ri = f?D:B;
    for(int k2=0;k2<32;k2++){
      __m512 xr=Rr[k2],xi=Ri[k2], tr=t4r[c][k2], ti=t4i[c][k2];
      Vr[c][k2]=_mm512_fmsub_ps(xr,tr,_mm512_mul_ps(xi,ti));
      Vi[c][k2]=_mm512_fmadd_ps(xr,ti,_mm512_mul_ps(xi,tr));
    }
  }
  /* Accumulators are four vectors per bin, so they go on the stack only while
     that stays small.  Bins finer than 16 samples are not what this is for; the
     caller gets -1 and the generic path handles it. */
  enum { MAXB = 64 };
  const long nb=(we-ws+(long)binsize-1)/(long)binsize;
  if(nb>MAXB) return -1;
  const __m512 NEG=_mm512_set1_ps(-1.f);
  __m512 Tr[32],Ti[32];
  const int full=(ws<=0 && we>=1024);
  /* One bin - the whole window - is the common case at this size, and then the
     four accumulators fit in registers.  Indexed by a variable they would not,
     and every block would become a 256-byte load-modify-store: that cost this
     path 1.7x against the top-K scan before it was split out. */
  if(nb==1){
    /* Four independent accumulator sets, combined at the end.  A single running
       maximum is a loop-carried dependency - each compare waits on the previous
       blend - and over 64 blocks that chain, not the work, sets the runtime.
       The top-K scan does not have this problem because it compares against a
       loop-invariant threshold, which is why it was winning here. */
    /* Prime the running maximum with the detection floor.  A bin only ever
       reports something above it, so starting there is exact - and it turns the
       four blends into a branch that is almost never taken, which is the whole
       reason the top-K scan was beating this. */
    const float t2p = thr>0.f ? thr*thr : -1.f;
    __m512 am0=_mm512_set1_ps(t2p),ar0=_mm512_setzero_ps(),ai0=_mm512_setzero_ps();
    __m512i ax0=_mm512_set1_epi32(-1);
    const __m512i STEP=_mm512_set1_epi32(32);
    for(int d=0;d<2;d++){
      for(int c=0;c<2;c++){ t16(&Vr[c][16*d],&Tr[16*c]); t16(&Vi[c][16*d],&Ti[16*c]); }
      int f2=fft32_84(Tr,Ti,A,B,1);
      __m512*Rr=f2?A:Tr, *Ri=f2?B:Ti;
      /* k0 advances by a constant, so carry it as a vector and add.  Broadcasting
         it from a GPR every iteration put a ~6-cycle move in the dependency chain
         and was costing more than the compare and all four blends together. */
      __m512i kv=_mm512_set1_epi32(16*d);
      for(int k1=0;k1<32;k1++,kv=_mm512_add_epi32(kv,STEP)){
        __m512 r=Rr[k1], i=Ri[k1];
        long k0=k1*32+16*d;
        __mmask16 inw=0xFFFF;
        if(!full){
          if(k0+16<=ws || k0>=we) continue;
          if(k0<ws || k0+16>we){ inw=0;
            for(int l=0;l<16;l++){ long k=k0+l; if(k>=ws&&k<we) inw|=(__mmask16)(1u<<l); } }
        }
        __m512 m2=_mm512_fmadd_ps(r,r,_mm512_mul_ps(i,i));
        if(inw!=0xFFFF) m2=_mm512_mask_blend_ps(inw,NEG,m2);
        __mmask16 g=_mm512_cmp_ps_mask(m2,am0,_CMP_GT_OQ);
        if(__builtin_expect(g!=0,0)){
          am0=_mm512_mask_blend_ps(g,am0,m2);
          ar0=_mm512_mask_blend_ps(g,ar0,r);
          ai0=_mm512_mask_blend_ps(g,ai0,i);
          ax0=_mm512_mask_blend_epi32(g,ax0,kv);
        }
      }
    }
    float mv[16],rv[16],iv[16]; int xv[16];
    _mm512_storeu_ps(mv,am0); _mm512_storeu_ps(rv,ar0);
    _mm512_storeu_ps(iv,ai0); _mm512_storeu_si512(xv,ax0);
    int bl=-1;
    for(int l=0;l<16;l++) if(xv[l]>=0 && (bl<0 || mv[l]>mv[bl])) bl=l;
    const float t2a = thr>0.f ? thr*thr : -1.f;
    if(bl<0 || mv[bl]<=t2a){ out[0].index=-1; out[0].re=0.f; out[0].im=0.f; out[0].magnitude=0.f; }
    else { out[0].index=(long)xv[bl]+bl; out[0].re=rv[bl];
           out[0].im=conj?-iv[bl]:iv[bl]; out[0].magnitude=sqrtf(mv[bl]); }
    return 0;
  }
  return fft1024_binmax_many(Vr,Vi,A,B,Tr,Ti,nb,binsize,thr,out,conj,ws,we,full,NEG);
}

/* Many-bin tail, deliberately out of line: its accumulators are four vectors per
   bin, and having them in the single-bin function's frame pushed that frame to
   ~32 KiB and cost more than the scan itself. */
__attribute__((noinline))
static int fft1024_binmax_many(__m512 Vr[2][32],__m512 Vi[2][32],
                               __m512 *A,__m512 *B,__m512 *Tr,__m512 *Ti,
                               long nb,size_t binsize,float thr,ap_peak *out,
                               int conj,long ws,long we,int full,__m512 NEG){
  enum { MAXB = 64 };
  __m512 bm[MAXB],br[MAXB],bi[MAXB]; __m512i bx[MAXB];
  const __m512 PRIME = thr>0.f ? _mm512_set1_ps(thr*thr) : NEG;
  for(long j=0;j<nb;j++){ bm[j]=PRIME; br[j]=_mm512_setzero_ps();
                          bi[j]=_mm512_setzero_ps(); bx[j]=_mm512_set1_epi32(-1); }
  for(int d=0;d<2;d++){
    for(int c=0;c<2;c++){ t16(&Vr[c][16*d],&Tr[16*c]); t16(&Vi[c][16*d],&Ti[16*c]); }
    int f=fft32_84(Tr,Ti,A,B,1);
    __m512*Rr=f?A:Tr, *Ri=f?B:Ti;
    for(int k1=0;k1<32;k1++){
      __m512 r=Rr[k1], i=Ri[k1];
      long k0=k1*32+16*d;
      __mmask16 inw=0xFFFF;
      if(!full){
        if(k0+16<=ws || k0>=we) continue;
        if(k0<ws || k0+16>we){ inw=0;
          for(int l=0;l<16;l++){ long k=k0+l; if(k>=ws&&k<we) inw|=(__mmask16)(1u<<l); } }
      }
      __m512 m2=_mm512_fmadd_ps(r,r,_mm512_mul_ps(i,i));
      if(inw!=0xFFFF) m2=_mm512_mask_blend_ps(inw,NEG,m2);
      long j0=(k0-ws)/(long)binsize, j1=(k0+15-ws)/(long)binsize;
      if(j0==j1){
        __mmask16 g=_mm512_cmp_ps_mask(m2,bm[j0],_CMP_GT_OQ);
        if(__builtin_expect(g!=0,0)){
          bm[j0]=_mm512_mask_blend_ps(g,bm[j0],m2);
          br[j0]=_mm512_mask_blend_ps(g,br[j0],r);
          bi[j0]=_mm512_mask_blend_ps(g,bi[j0],i);
          bx[j0]=_mm512_mask_blend_epi32(g,bx[j0],_mm512_set1_epi32((int)k0));
        }
      } else {
        for(int l=0;l<16;l++){
          if(!((inw>>l)&1)) continue;
          long j=(k0+l-ws)/(long)binsize;
          __mmask16 one=(__mmask16)(1u<<l);
          if(_mm512_cmp_ps_mask(m2,bm[j],_CMP_GT_OQ)&one){
            bm[j]=_mm512_mask_blend_ps(one,bm[j],m2);
            br[j]=_mm512_mask_blend_ps(one,br[j],r);
            bi[j]=_mm512_mask_blend_ps(one,bi[j],i);
            bx[j]=_mm512_mask_blend_epi32(one,bx[j],_mm512_set1_epi32((int)k0));
          }
        }
      }
    }
  }
  const float t2 = thr>0.f ? thr*thr : -1.f;
  for(long j=0;j<nb;j++){
    float mv[16],rv[16],iv[16]; int xv[16];
    _mm512_storeu_ps(mv,bm[j]); _mm512_storeu_ps(rv,br[j]);
    _mm512_storeu_ps(iv,bi[j]); _mm512_storeu_si512(xv,bx[j]);
    int bl=-1;
    for(int l=0;l<16;l++) if(xv[l]>=0 && (bl<0 || mv[l]>mv[bl])) bl=l;
    if(bl<0 || mv[bl]<=t2){ out[j].index=-1; out[j].re=0.f; out[j].im=0.f; out[j].magnitude=0.f; continue; }
    out[j].index=(long)xv[bl]+bl;
    out[j].re=rv[bl]; out[j].im=conj?-iv[bl]:iv[bl];
    out[j].magnitude=sqrtf(mv[bl]);
  }
  return 0;
}
