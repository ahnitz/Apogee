/* Matched filter against the baseline a user would otherwise write.
 *
 * Baseline: forward-transform every segment once, then per pair form the product
 * and inverse-transform it, then scan for the peak.  That is the same algorithm
 * with the same reuse - the only difference is the library underneath - so this
 * isolates what apogee's peak-only path is worth on this workload.
 *
 * Both FFTW variants get batched plans; MKL gets a descriptor.  The scan for the
 * baselines is a plain max over the window, which is the cheapest thing that
 * produces the same answer.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <dlfcn.h>
#include "mkl_dfti.h"
#include "fftw_min.h"
#include "apogee.h"
#include "transform.h"

static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+1e-9*t.tv_nsec;}
static unsigned long long rs=88172645463325252ULL;
static double u(void){rs^=rs<<13;rs^=rs>>7;rs^=rs<<17;return (double)(rs>>11)/9007199254740992.0;}
static double gauss(void){return sqrt(-2.0*log(u()+1e-300))*cos(2.0*M_PI*u());}
static int cmpd(const void*a,const void*b){double x=*(const double*)a,y=*(const double*)b;return x<y?-1:x>y;}

/* The baselines get vectorised versions of everything apogee vectorises - the
   product and the per-bin peak scan.  A scalar loop in either place would be a
   straw man: the comparison is against a competent implementation of the same
   algorithm, not against the first thing one might type. */
#include <immintrin.h>
__attribute__((target("avx512f")))
static void base_mul(const float *a,const float *b,float *o,size_t n){
  const __m512i EV=_mm512_setr_epi32(0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30);
  const __m512i OD=_mm512_setr_epi32(1,3,5,7,9,11,13,15,17,19,21,23,25,27,29,31);
  const __m512i LO=_mm512_setr_epi32(0,16,1,17,2,18,3,19,4,20,5,21,6,22,7,23);
  const __m512i HI=_mm512_setr_epi32(8,24,9,25,10,26,11,27,12,28,13,29,14,30,15,31);
  for(size_t k=0;k<n;k+=16){
    __m512 a0=_mm512_loadu_ps(a+2*k),a1=_mm512_loadu_ps(a+2*k+16);
    __m512 b0=_mm512_loadu_ps(b+2*k),b1=_mm512_loadu_ps(b+2*k+16);
    __m512 ar=_mm512_permutex2var_ps(a0,EV,a1), ai=_mm512_permutex2var_ps(a0,OD,a1);
    __m512 br=_mm512_permutex2var_ps(b0,EV,b1), bi=_mm512_permutex2var_ps(b0,OD,b1);
    __m512 pr=_mm512_fmsub_ps(ar,br,_mm512_mul_ps(ai,bi));
    __m512 pi=_mm512_fmadd_ps(ar,bi,_mm512_mul_ps(ai,br));
    _mm512_storeu_ps(o+2*k,   _mm512_permutex2var_ps(pr,LO,pi));
    _mm512_storeu_ps(o+2*k+16,_mm512_permutex2var_ps(pr,HI,pi));
  }
}

/* Per-bin maximum of |z|^2 over an interleaved complex array, vectorised the
   same way apogee does it internally.  Returns the winning index and value. */
__attribute__((target("avx2,fma")))
static void base_binmax(const float *z,size_t lo,size_t hi,size_t *bidx,float *bmax){
  __m256 mx=_mm256_set1_ps(-1.f);
  __m256i ix=_mm256_set1_epi32(-1);
  size_t k=lo;
  for(; k+4<=hi; k+=4){
    __m256 v=_mm256_loadu_ps(z+2*k);            /* r0 i0 r1 i1 r2 i2 r3 i3 */
    __m256 sq=_mm256_mul_ps(v,v);
    /* horizontal pairs: r^2+i^2 for four complex, broadcast into 8 lanes */
    __m256 m=_mm256_hadd_ps(sq,sq);             /* m0 m1 m0 m1 m2 m3 m2 m3 */
    __m256 cand=_mm256_permutevar8x32_ps(m,_mm256_setr_epi32(0,1,4,5,0,1,4,5));
    __m256i kv=_mm256_add_epi32(_mm256_set1_epi32((int)k),
                                _mm256_setr_epi32(0,1,2,3,0,1,2,3));
    __m256 g=_mm256_cmp_ps(cand,mx,_CMP_GT_OQ);
    mx=_mm256_blendv_ps(mx,cand,g);
    ix=_mm256_castps_si256(_mm256_blendv_ps(_mm256_castsi256_ps(ix),
                                            _mm256_castsi256_ps(kv),g));
  }
  float mv[8]; int iv[8];
  _mm256_storeu_ps(mv,mx); _mm256_storeu_si256((__m256i*)iv,ix);
  float best=-1.f; size_t bi=lo;
  for(int l=0;l<4;l++) if(iv[l]>=0 && mv[l]>best){ best=mv[l]; bi=(size_t)iv[l]; }
  for(; k<hi; k++){
    float m=z[2*k]*z[2*k]+z[2*k+1]*z[2*k+1];
    if(m>best){ best=m; bi=k; }
  }
  *bidx=bi; *bmax=best;
}

int main(int argc,char**argv){
  int lg = argc>1?atoi(argv[1]):14;
  int D  = argc>2?atoi(argv[2]):16;
  int T  = argc>3?atoi(argv[3]):16;
  size_t n=(size_t)1<<lg;
  size_t ws=(size_t)(0.2*n)&~15UL, we=ws+((size_t)(0.6*n)&~15UL);
  size_t bs = n<1024?n:1024;

  float *data=aligned_alloc(64,(size_t)D*2*n*4), *tmpl=aligned_alloc(64,(size_t)T*2*n*4);
  for(size_t i=0;i<(size_t)D*2*n;i++) data[i]=(float)gauss();
  for(size_t i=0;i<(size_t)T*2*n;i++) tmpl[i]=(float)gauss();

  /* ---- apogee ---- */
  /* Everything downstream takes spectra: the caller's pipeline has them in the
     frequency domain, so the D+T forward transforms are outside the comparison
     for apogee and the baselines alike. */
  ap_plan *fp=ap_create(n);
  float *dspec0=aligned_alloc(64,(size_t)D*2*n*4), *tspec0=aligned_alloc(64,(size_t)T*2*n*4);
  for(int i=0;i<D;i++) ap_fft(fp,data+(size_t)i*2*n,dspec0+(size_t)i*2*n,AP_FORWARD);
  for(int i=0;i<T;i++) ap_fft(fp,tmpl+(size_t)i*2*n,tspec0+(size_t)i*2*n,AP_FORWARD);

  ap_mf_plan *mp=ap_mf_create(n,D,T);
  for(int i=0;i<D;i++) ap_mf_set_data(mp,i,dspec0+(size_t)i*2*n);
  for(int i=0;i<T;i++) ap_mf_set_template(mp,i,tspec0+(size_t)i*2*n);
  size_t nb=ap_mf_nbins(mp,bs,ws,we);
  ap_peak *pk=malloc((size_t)D*T*nb*sizeof(ap_peak));
  int *cnt=malloc((size_t)D*T*sizeof(int));
  ap_mf_run(mp,0,D,0,T,bs,0.f,pk,cnt,ws,we);
  float mx=0; for(size_t i=0;i<(size_t)D*T*nb;i++) if(pk[i].magnitude>mx) mx=pk[i].magnitude;
  float THR=mx*0.8f;

  /* ---- baselines: spectra, then per pair product + inverse + scan ---- */
  int nn=(int)n;
  fftwf_import_wisdom_from_filename("amdfftw.wisdom");
  fftwf_complex *fa=fftwf_alloc_complex(n),*fb=fftwf_alloc_complex(n);
  fftwf_plan abwd=fftwf_plan_dft_1d(nn,fa,fb,FFTW_BACKWARD,FFTW_MEASURE);
  DFTI_DESCRIPTOR_HANDLE h;
  DftiCreateDescriptor(&h,DFTI_SINGLE,DFTI_COMPLEX,1,(MKL_LONG)n);
  DftiSetValue(h,DFTI_PLACEMENT,DFTI_NOT_INPLACE); DftiCommitDescriptor(h);

  float *ds=aligned_alloc(64,(size_t)D*2*n*4), *ts=aligned_alloc(64,(size_t)T*2*n*4);
  float *prod=aligned_alloc(64,2*n*4), *outb=aligned_alloc(64,2*n*4);

  /* baselines get the same spectra, conjugating templates once as we do */
  memcpy(ds,dspec0,(size_t)D*2*n*4);
  for(int i=0;i<T;i++){ memcpy(ts+(size_t)i*2*n,tspec0+(size_t)i*2*n,2*n*4);
    float *q=ts+(size_t)i*2*n; for(size_t k=0;k<n;k++) q[2*k+1]=-q[2*k+1]; }
  #define PAIRLOOP(INV) do{                                                  \
    for(int d=0;d<D;d++) for(int t=0;t<T;t++){                               \
      const float *A=ds+(size_t)d*2*n,*B=ts+(size_t)t*2*n;                   \
      base_mul(A,B,prod,n);                                                  \
      INV(prod,outb);                                                        \
      for(size_t j=0;j<nb;j++){ size_t lo=ws+j*bs,hi=lo+bs; if(hi>we)hi=we;  \
        size_t bi2; float best;                                              \
        base_binmax(outb,lo,hi,&bi2,&best);                                  \
        sink+=bi2+(size_t)(sqrtf(best)>THR); }                               \
    } }while(0)

  volatile size_t sink=0;
  #define MKLB(in,out) DftiComputeBackward(h,(void*)(in),(out))
  /* execute_dft runs the plan on other arrays, so amd-fftw is not charged for a
     copy in and out */
  #define AMDB(in,out) fftwf_execute_dft(abwd,(fftwf_complex*)(in),(fftwf_complex*)(out))

  double bm=1e30,ba=1e30,bp=1e30,t0;
  int reps = n<=(1u<<14)?3:1;
  for(int r=0;r<reps;r++){ t0=now(); PAIRLOOP(MKLB); double t=now()-t0; if(t<bm)bm=t; }
  for(int r=0;r<reps;r++){ t0=now(); PAIRLOOP(AMDB); double t=now()-t0; if(t<ba)ba=t; }
  for(int r=0;r<reps+2;r++){ t0=now();
    for(int i=0;i<D;i++) ap_mf_set_data(mp,i,dspec0+(size_t)i*2*n);
    for(int i=0;i<T;i++) ap_mf_set_template(mp,i,tspec0+(size_t)i*2*n);
    ap_mf_run(mp,0,D,0,T,bs,THR,pk,cnt,ws,we);
    double t=now()-t0; if(t<bp)bp=t; }

  double np=(double)D*T;
  printf("N=2^%-2d  D=%d T=%d  (%d pairs, 60%% window, bin %zu, floor on)\n",lg,D,T,(int)np,bs);
  printf("  all three are given spectra; forward transforms are outside the timing\n");
  printf("  %-24s %10.1f us total  %9.3f us/pair\n","MKL",bm*1e6,bm*1e6/np);
  printf("  %-24s %10.1f us total  %9.3f us/pair\n","amd-fftw",ba*1e6,ba*1e6/np);
  printf("  %-24s %10.1f us total  %9.3f us/pair   vs MKL %.2fx  vs amd %.2fx\n",
         "apogee (incl. ingest)",bp*1e6,bp*1e6/np,bm/bp,ba/bp);
  printf("  (sink %zu)\n",(size_t)sink);
  return 0;
}
