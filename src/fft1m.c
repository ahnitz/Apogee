/* peakfft: N=2^20 (1024x1024) four-step back end.
   Original design notes:
   N=2^20 four-step 1024x1024.
   n = n2*1024 + n1  (n1 fast/contiguous)
   stage1: for each n1, DFT over n2 (stride 1024), SIMD across 16 consecutive n1
           -> loads are 128B full-cache-line granules, lanes ARE the intermediate column index
   twiddle W_N[n1*k2]; intermediate stored as inter[k2*1024 + n1] (SoA)
   stage2: for each k2, contiguous 1024-pt FFT over n1 -> X[k1*1024 + k2]           */
#define _GNU_SOURCE
#include <sys/mman.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include <immintrin.h>
#include "codelets.h"
#include <time.h>
#ifdef PF_PROFILE
double pf_t1=0,pf_t2=0;
static double nw(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+1e-9*t.tv_nsec;}
#define PROF_A double _a=nw()
#define PROF_B pf_t1+=nw()-_a; double _b=nw()
#define PROF_C pf_t2+=nw()-_b
#else
#define PROF_A
#define PROF_B
#define PROF_C
#endif

#include "internal.h"
#include "transpose16.h"

/* N = N1 * N2 with N1 fixed at 1024, so stage 2 is always the validated
   L1-resident 1024-point kernel and only N2 = N/1024 varies (4 .. 1024,
   i.e. N = 2^12 .. 2^20). */
#define PF_N1 1024
struct P20 {
  size_t N; int N2; unsigned Nmask16;   /* Nmask16 = N/16 - 1 */
  float *wM_r,*wM_i;                /* W_N2[j], for the generic element-space FFT */
  float *inter_re,*inter_im;
  __m512 *bufR,*bufI,*scrR,*scrI;   /* 1024 each = 64 KiB each */
  __m512 *TLr,*TLi;                 /* [1024] lanes l: W_N[l*k2] */
  float *w1024r,*w1024i;            /* inner four-step twiddle */
  float *w256r,*w256i,*wlor,*wloi;  /* 2-level table for W_65536[g*k2] */
  __m512 t4r[2][32],t4i[2][32];     /* for fft1024_soa */
  short *q;                         /* int16 BFP intermediate: q[k2][g][16 re | 16 im] */
  float *scl;                       /* per-(k2,g) dequant scale */
  signed char *res;                 /* int8 residual plane, layout [g][k2][16re|16im] (write-sequential) */
};

P20* pf20_create(size_t Nin){
  P20*p=aligned_alloc(64,sizeof(P20)); memset(p,0,sizeof(P20));
  const double N=(double)Nin;
  int N2=(int)(Nin/PF_N1);
  p->N=Nin; p->N2=N2; p->Nmask16=(unsigned)(Nin/16-1);
  size_t inter_bytes=(size_t)Nin*4;
  p->inter_re=aligned_alloc(2u<<20,inter_bytes); p->inter_im=aligned_alloc(2u<<20,inter_bytes);
  madvise(p->inter_re,inter_bytes,MADV_HUGEPAGE); madvise(p->inter_im,inter_bytes,MADV_HUGEPAGE);
  size_t bufslots = (N2==1024) ? 1056 : (size_t)N2;   /* 1024 path uses stride-33 padding */
  p->bufR=aligned_alloc(64,bufslots*64); p->bufI=aligned_alloc(64,bufslots*64);
  p->scrR=aligned_alloc(64,bufslots*64); p->scrI=aligned_alloc(64,bufslots*64);
  p->TLr=aligned_alloc(64,(size_t)N2*64);  p->TLi=aligned_alloc(64,(size_t)N2*64);
  p->wM_r=aligned_alloc(64,(size_t)N2*4);  p->wM_i=aligned_alloc(64,(size_t)N2*4);
  for(int j=0;j<N2;j++){ double a=-2.0*M_PI*j/(double)N2; p->wM_r[j]=(float)cos(a); p->wM_i[j]=(float)sin(a); }
  for(int k2=0;k2<N2;k2++){
    float tr[16],ti[16];
    for(int l=0;l<16;l++){ double a=-2.0*M_PI*(double)l*k2/N; tr[l]=cosf(a); ti[l]=sinf(a); }
    p->TLr[k2]=_mm512_loadu_ps(tr); p->TLi[k2]=_mm512_loadu_ps(ti);
  }
  { size_t qb=(size_t)N2*2048*2, rb=(size_t)64*N2*32;
    p->q=aligned_alloc(2u<<20,qb<(2u<<20)?(2u<<20):qb); madvise(p->q,qb,MADV_HUGEPAGE);
    p->scl=aligned_alloc(64,(size_t)N2*64*4);
    p->res=aligned_alloc(2u<<20,rb<(2u<<20)?(2u<<20):rb); madvise(p->res,rb,MADV_HUGEPAGE); }
  p->w1024r=aligned_alloc(64,1024*4); p->w1024i=aligned_alloc(64,1024*4);
  for(int j=0;j<1024;j++){ double a=-2.0*M_PI*j/1024.0; p->w1024r[j]=cos(a); p->w1024i[j]=sin(a); }
  { size_t nhi=(size_t)(Nin/16)/256; if(nhi<1) nhi=1;
    double Nq=(double)(Nin/16);
    p->w256r=aligned_alloc(64,nhi*4+64); p->w256i=aligned_alloc(64,nhi*4+64);
    p->wlor =aligned_alloc(64,256*4);    p->wloi =aligned_alloc(64,256*4);
    for(size_t j=0;j<nhi;j++){ double a=-2.0*M_PI*(double)(j*256)/Nq;
      p->w256r[j]=(float)cos(a); p->w256i[j]=(float)sin(a); }
    for(int j=0;j<256;j++){ double b=-2.0*M_PI*(double)j/Nq;
      p->wlor[j]=(float)cos(b); p->wloi[j]=(float)sin(b); }
  }
  for(int c=0;c<2;c++)for(int k2=0;k2<32;k2++){
    float tr[16],ti[16];
    for(int l=0;l<16;l++){ int n1=16*c+l; double a=-2.0*M_PI*(double)n1*k2/1024.0; tr[l]=cos(a); ti[l]=sin(a); }
    p->t4r[c][k2]=_mm512_loadu_ps(tr); p->t4i[c][k2]=_mm512_loadu_ps(ti);
  }
  return p;
}


/* Generic element-space Stockham FFT of size M (a power of two, 2..512).
   Operates on an array of __m512 elements; the 16 SIMD lanes are independent
   transforms, so every twiddle is a broadcast scalar and no shuffles occur.
   Result lands in X when the stage count is even, otherwise in Y (returned). */
#define CMULB(orr,oii,ar,ai,cr,ci) do{                              \
    __m512 _cr=_mm512_set1_ps(cr), _ci=_mm512_set1_ps(ci);          \
    (orr)=_mm512_fmsub_ps(ar,_cr,_mm512_mul_ps(ai,_ci));            \
    (oii)=_mm512_fmadd_ps(ar,_ci,_mm512_mul_ps(ai,_cr)); }while(0)

int elem_fft_generic(int M,__m512*Xr,__m512*Xi,__m512*Yr,__m512*Yi,
                            const float*wr,const float*wi){
  const __m512 Z=_mm512_setzero_ps();
  int n=M,s=1,flip=0;
  while(n>1){
    int r=(n%4==0)?4:2, m=n/r;
    for(int j=0;j<m;j++){
      for(int q=0;q<s;q++){
        int i0=q+s*j;
        if(r==4){
          int i1=i0+s*m, i2=i1+s*m, i3=i2+s*m;
          __m512 a0r=Xr[i0],a0i=Xi[i0], a1r=Xr[i1],a1i=Xi[i1];
          __m512 a2r=Xr[i2],a2i=Xi[i2], a3r=Xr[i3],a3i=Xi[i3];
          __m512 t0r=_mm512_add_ps(a0r,a2r), t0i=_mm512_add_ps(a0i,a2i);
          __m512 t1r=_mm512_sub_ps(a0r,a2r), t1i=_mm512_sub_ps(a0i,a2i);
          __m512 t2r=_mm512_add_ps(a1r,a3r), t2i=_mm512_add_ps(a1i,a3i);
          __m512 dr =_mm512_sub_ps(a1r,a3r), di =_mm512_sub_ps(a1i,a3i);
          __m512 t3r=di, t3i=_mm512_sub_ps(Z,dr);            /* -i*(a1-a3) */
          __m512 o0r=_mm512_add_ps(t0r,t2r), o0i=_mm512_add_ps(t0i,t2i);
          __m512 o1r=_mm512_add_ps(t1r,t3r), o1i=_mm512_add_ps(t1i,t3i);
          __m512 o2r=_mm512_sub_ps(t0r,t2r), o2i=_mm512_sub_ps(t0i,t2i);
          __m512 o3r=_mm512_sub_ps(t1r,t3r), o3i=_mm512_sub_ps(t1i,t3i);
          int o=q+s*4*j;
          Yr[o]=o0r; Yi[o]=o0i;                              /* twiddle l=0 is 1 */
          int b=(j*s)&(M-1), b2=(2*b)&(M-1), b3=(3*b)&(M-1);
          CMULB(Yr[o+s],  Yi[o+s],  o1r,o1i, wr[b],  wi[b]);
          CMULB(Yr[o+2*s],Yi[o+2*s],o2r,o2i, wr[b2], wi[b2]);
          CMULB(Yr[o+3*s],Yi[o+3*s],o3r,o3i, wr[b3], wi[b3]);
        } else {
          int i1=i0+s*m;
          __m512 a0r=Xr[i0],a0i=Xi[i0], a1r=Xr[i1],a1i=Xi[i1];
          int o=q+s*2*j, b=(j*s)&(M-1);
          Yr[o]=_mm512_add_ps(a0r,a1r); Yi[o]=_mm512_add_ps(a0i,a1i);
          __m512 dr=_mm512_sub_ps(a0r,a1r), di=_mm512_sub_ps(a0i,a1i);
          CMULB(Yr[o+s],Yi[o+s], dr,di, wr[b], wi[b]);
        }
      }
    }
    { __m512*t; t=Xr;Xr=Yr;Yr=t; t=Xi;Xi=Yi;Yi=t; }
    flip^=1; n=m; s*=r;
  }
  return flip;
}

/* element-space 1024-pt FFT across the group buffer (lanes independent) */
static void elem_fft1024(P20*p){
  __m512 *bR=p->bufR,*bI=p->bufI,*sR=p->scrR,*sI=p->scrI;
  for(int e1=0;e1<32;e1++) fft32_84(bR+e1,bI+e1,sR+e1,sI+e1,33);
  for(int k2p=0;k2p<32;k2p++) for(int e1=0;e1<32;e1++){
    int idx=e1+33*k2p, t=(e1*k2p)&1023;
    __m512 wr=_mm512_set1_ps(p->w1024r[t]), wi=_mm512_set1_ps(p->w1024i[t]);
    __m512 xr=bR[idx],xi=bI[idx];
    bR[idx]=_mm512_fmsub_ps(xr,wr,_mm512_mul_ps(xi,wi));
    bI[idx]=_mm512_fmadd_ps(xr,wi,_mm512_mul_ps(xi,wr));
  }
  for(int k2p=0;k2p<32;k2p++) fft32_84(bR+33*k2p,bI+33*k2p,sR+33*k2p,sI+33*k2p,1);
}

static void stage1(P20*p,const float*in,int conj){
  const int N2=p->N2;
  const unsigned NM=p->Nmask16;
  const size_t resstride=(size_t)N2*32;
  const __m512 sg=conj?_mm512_castsi512_ps(_mm512_set1_epi32((int)0x80000000)):_mm512_setzero_ps();
  const __m512i ev=_mm512_setr_epi32(0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30);
  const __m512i od=_mm512_setr_epi32(1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31);
  for(int g=0;g<64;g++){
    const float*src=in+2*(16*g);
    for(int n2=0;n2<N2;n2++){
      if(n2+8<N2) _mm_prefetch((const char*)(src+(size_t)(n2+8)*2048),_MM_HINT_T0);
      __m512 a=_mm512_loadu_ps(src+(size_t)n2*2048), b=_mm512_loadu_ps(src+(size_t)n2*2048+16);
      int q=(N2==1024)?((n2&31)+33*(n2>>5)):n2;
      p->bufR[q]=_mm512_permutex2var_ps(a,ev,b);
      p->bufI[q]=_mm512_xor_ps(_mm512_permutex2var_ps(a,od,b),sg);
    }
    __m512 *RR=p->bufR,*RI=p->bufI;
    if(N2==1024) elem_fft1024(p);
    else if(N2>1){
      int f=elem_fft_generic(N2,p->bufR,p->bufI,p->scrR,p->scrI,p->wM_r,p->wM_i);
      if(f){ RR=p->scrR; RI=p->scrI; }
    }
    for(int k2=0;k2<N2;k2++){
      int eb=(N2==1024)?(33*(k2&31)+(k2>>5)):k2;
      unsigned m=((unsigned)g*(unsigned)k2)&NM; unsigned m1=m>>8, m0=m&255;
      float sr=p->w256r[m1]*p->wlor[m0]-p->w256i[m1]*p->wloi[m0];
      float si=p->w256r[m1]*p->wloi[m0]+p->w256i[m1]*p->wlor[m0];
      __m512 SR=_mm512_set1_ps(sr),SI=_mm512_set1_ps(si);
      __m512 tr=_mm512_fmsub_ps(SR,p->TLr[k2],_mm512_mul_ps(SI,p->TLi[k2]));
      __m512 ti=_mm512_fmadd_ps(SR,p->TLi[k2],_mm512_mul_ps(SI,p->TLr[k2]));
      __m512 xr=RR[eb],xi=RI[eb];
      __m512 vr=_mm512_fmsub_ps(xr,tr,_mm512_mul_ps(xi,ti));
      __m512 vi=_mm512_fmadd_ps(xr,ti,_mm512_mul_ps(xi,tr));
      float mx=_mm512_reduce_max_ps(_mm512_max_ps(_mm512_abs_ps(vr),_mm512_abs_ps(vi)));
      float sc = mx>0.f ? 8388607.0f/mx : 1.f;         /* 24-bit */
      p->scl[k2*64+g] = mx>0.f ? mx*(1.0f/8388607.0f) : 1.f;
      __m512 vs=_mm512_set1_ps(sc);
      const __m512i CMAX=_mm512_set1_epi32( 8388607), CMIN=_mm512_set1_epi32(-8388607);
      __m512i xr24=_mm512_max_epi32(CMIN,_mm512_min_epi32(CMAX,_mm512_cvtps_epi32(_mm512_mul_ps(vr,vs))));
      __m512i xi24=_mm512_max_epi32(CMIN,_mm512_min_epi32(CMAX,_mm512_cvtps_epi32(_mm512_mul_ps(vi,vs))));
      /* hi 16 bits (arithmetic shift keeps sign) -> screening plane */
      __m256i pr=_mm512_cvtepi32_epi16(_mm512_srai_epi32(xr24,8));
      __m256i pi=_mm512_cvtepi32_epi16(_mm512_srai_epi32(xi24,8));
      short*dst=p->q+(size_t)k2*2048+32*g;
      _mm256_stream_si256((__m256i*)dst,pr);
      _mm256_stream_si256((__m256i*)(dst+16),pi);
      /* low 8 bits -> residual plane, written sequentially in k2 for fixed g */
      __m128i rr8=_mm512_cvtepi32_epi8(_mm512_and_epi32(xr24,_mm512_set1_epi32(255)));
      __m128i ri8=_mm512_cvtepi32_epi8(_mm512_and_epi32(xi24,_mm512_set1_epi32(255)));
      signed char*rd=p->res+(size_t)g*resstride+(size_t)k2*32;
      _mm_stream_si128((__m128i*)rd,rr8);
      _mm_stream_si128((__m128i*)(rd+16),ri8);
    }
  }
  _mm_sfence();
}

/* rebuild one intermediate column at full 24-bit precision */
static void rebuild24(P20*p,int k2,float*re,float*im){
  const short*src=p->q+(size_t)k2*2048; const float*sp=p->scl+k2*64;
  const size_t resstride=(size_t)p->N2*32;
  for(int g=0;g<64;g++){
    const signed char*rd=p->res+(size_t)g*resstride+(size_t)k2*32;
    __m512 vs=_mm512_set1_ps(sp[g]);
    __m512i hr=_mm512_slli_epi32(_mm512_cvtepi16_epi32(_mm256_load_si256((const __m256i*)(src+32*g))),8);
    __m512i hi_=_mm512_slli_epi32(_mm512_cvtepi16_epi32(_mm256_load_si256((const __m256i*)(src+32*g+16))),8);
    __m512i lr=_mm512_cvtepu8_epi32(_mm_loadu_si128((const __m128i*)rd));
    __m512i li=_mm512_cvtepu8_epi32(_mm_loadu_si128((const __m128i*)(rd+16)));
    _mm512_store_ps(re+16*g,_mm512_mul_ps(_mm512_cvtepi32_ps(_mm512_or_epi32(hr,lr)),vs));
    _mm512_store_ps(im+16*g,_mm512_mul_ps(_mm512_cvtepi32_ps(_mm512_or_epi32(hi_,li)),vs));
  }
}

/* Exact full transform.  Stage 2 is run 16 columns at a time so the output,
   which is naturally strided by 1024 complex, can be written back as contiguous
   128-byte runs via a 16x16 register transpose instead of an 8-byte scatter. */
void pf20_exact(P20*p,const float*in,float*out,int conj){
  /* Non-temporal stores need a 64-byte-aligned destination; callers (numpy, say)
     do not always provide one, so fall back to unaligned stores when they don't. */
  const int nt = (((uintptr_t)out) & 63u) == 0u;
  static float stg_re[16*1024] __attribute__((aligned(64)));
  static float stg_im[16*1024] __attribute__((aligned(64)));
  const __m512i lo=_mm512_setr_epi32(0,16,1,17,2,18,3,19,4,20,5,21,6,22,7,23);
  const __m512i hi=_mm512_setr_epi32(8,24,9,25,10,26,11,27,12,28,13,29,14,30,15,31);
  const int N2=p->N2;
  const __m512 sg=conj?_mm512_castsi512_ps(_mm512_set1_epi32((int)0x80000000)):_mm512_setzero_ps();
  stage1(p,in,conj);
  if(N2<16){                       /* too few columns to block the corner turn */
    for(int k2=0;k2<N2;k2++){
      rebuild24(p,k2,stg_re,stg_im);
      pf_fft1024_soa(stg_re,stg_im,p->t4r,p->t4i);
      for(int k1=0;k1<PF_N1;k1++){ size_t k=(size_t)k1*N2+k2;
        out[2*k]=stg_re[k1]; out[2*k+1]=conj?-stg_im[k1]:stg_im[k1]; }
    }
    return;
  }
  for(int jb=0;jb<N2;jb+=16){
    for(int l=0;l<16;l++){
      rebuild24(p,jb+l,stg_re+l*1024,stg_im+l*1024);
      pf_fft1024_soa(stg_re+l*1024,stg_im+l*1024,p->t4r,p->t4i);
    }
    for(int k1b=0;k1b<1024;k1b+=16){
      __m512 A[16],B[16],TA[16],TB[16];
      for(int l=0;l<16;l++){ A[l]=_mm512_load_ps(stg_re+l*1024+k1b);
                             B[l]=_mm512_load_ps(stg_im+l*1024+k1b); }
      t16(A,TA); t16(B,TB);
      for(int r=0;r<16;r++){
        float*d=out+2*((size_t)(k1b+r)*N2+jb);
        __m512 vi=_mm512_xor_ps(TB[r],sg);
        __m512 o0=_mm512_permutex2var_ps(TA[r],lo,vi);
        __m512 o1=_mm512_permutex2var_ps(TA[r],hi,vi);
        if(nt){ _mm512_stream_ps(d,o0); _mm512_stream_ps(d+16,o1); }
        else  { _mm512_storeu_ps(d,o0); _mm512_storeu_ps(d+16,o1); }
      }
    }
  }
  _mm_sfence();
}

/* ---- top-K path: no output array is ever written ---- */


int pf20_topk(P20*p,const float*in,int Kreq,pf_peak*out,int conj,size_t ws,size_t we){
  int K=Kreq*2+8; if(K>256)K=256;
  PROF_A; stage1(p,in,conj); PROF_B;
  const int N2=p->N2;
  pf_cand T[256]; int nT=0;
  static float re[1024] __attribute__((aligned(64))), im[1024] __attribute__((aligned(64)));
  float thr=-1.f;
  for(int k2=0;k2<N2;k2++){
    { const short*src=p->q+(size_t)k2*2048; const float*sp=p->scl+k2*64;
      for(int g=0;g<64;g++){
        __m512 vs=_mm512_set1_ps(sp[g]*256.0f);
        __m512i a=_mm512_cvtepi16_epi32(_mm256_load_si256((const __m256i*)(src+32*g)));
        __m512i b=_mm512_cvtepi16_epi32(_mm256_load_si256((const __m256i*)(src+32*g+16)));
        _mm512_store_ps(re+16*g,_mm512_mul_ps(_mm512_cvtepi32_ps(a),vs));
        _mm512_store_ps(im+16*g,_mm512_mul_ps(_mm512_cvtepi32_ps(b),vs));
      } }
    pf_fft1024_soa(re,im,p->t4r,p->t4i);
    /* Priming uses a global per-lane maximum, which is only a valid bound when the
       whole range is in play; with a window it could sit above the windowed K-th
       largest and hide every real peak. */
    if(k2==0 && ws==0 && we>=p->N){ float t0=pf_prime_threshold(re,im,1024,K); if(t0>thr) thr=t0; }
    __m512 vthr=_mm512_set1_ps(thr);
    /* output index is (k1+l)*N2 + k2, so the window restricts k1 */
    long klo=((long)ws-k2+N2-1)/N2, khi=((long)we-1-k2)/N2;
    if(klo<0) klo=0;
    if(khi>1023) khi=1023;
    if(klo>khi) continue;
    for(long k1=klo&~15L;k1<=khi;k1+=16){
      __mmask16 inw=0xFFFF;
      if(k1<klo || k1+15>khi){
        inw=0;
        for(int l=0;l<16;l++){ long kk=k1+l;
          if(kk>=klo&&kk<=khi) inw|=(__mmask16)(1u<<l); }
        if(!inw) continue;
      }
      __m512 r=_mm512_load_ps(re+k1), i2=_mm512_load_ps(im+k1);
      __m512 m2=_mm512_fmadd_ps(r,r,_mm512_mul_ps(i2,i2));
      __mmask16 msk=_mm512_cmp_ps_mask(m2,vthr,_CMP_GT_OQ)&inw;
      if(msk){
        float b[16]; _mm512_storeu_ps(b,m2);
        while(msk){
          int l=__builtin_ctz((unsigned)msk); msk&=(__mmask16)(msk-1);
          if(b[l]<=thr) continue;
          pf_push(T,K,&nT,b[l],(k1+l)*N2+k2,re[k1+l],im[k1+l]);
          if(nT==K){ thr=T[0].mag2; vthr=_mm512_set1_ps(thr); }
        }
      }
    }
  }
  /* refine every candidate to 24-bit precision, then rank */
  for(int a=0;a<nT;a++){
    int k2=T[a].idx%N2, done=0;
    for(int b=0;b<a;b++) if(T[b].idx%N2==k2){ done=1; break; }
    if(done) continue;
    rebuild24(p,k2,re,im);
    pf_fft1024_soa(re,im,p->t4r,p->t4i);
    for(int b=a;b<nT;b++) if(T[b].idx%N2==k2){
      int k1=T[b].idx/N2; T[b].re=re[k1]; T[b].im=im[k1];
      T[b].mag2=re[k1]*re[k1]+im[k1]*im[k1];
    }
  }
  for(int a=1;a<nT;a++){ pf_cand v=T[a]; int b=a-1; while(b>=0&&T[b].mag2<v.mag2){T[b+1]=T[b];b--;} T[b+1]=v; }
  int nout = nT<Kreq?nT:Kreq;
  for(int a=0;a<nout;a++){ out[a].index=T[a].idx; out[a].re=T[a].re;
    out[a].im=conj?-T[a].im:T[a].im; out[a].magnitude=sqrtf(T[a].mag2); }
  PROF_C;
  return nout;
}

void pf20_destroy(P20*p){
  if(!p) return;
  free(p->inter_re); free(p->inter_im); free(p->bufR); free(p->bufI);
  free(p->scrR); free(p->scrI); free(p->TLr); free(p->TLi);
  free(p->w1024r); free(p->w1024i); free(p->w256r); free(p->w256i);
  free(p->wlor); free(p->wloi); free(p->q); free(p->scl); free(p->res); free(p);
}
