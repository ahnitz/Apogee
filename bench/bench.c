/* peakfft benchmark vs Intel MKL (DFTI) and FFTW (FFTW_PATIENT).
 *
 * Timing notes: the four implementations are run interleaved A/B/C/D inside each
 * timed block so drift and interference hit them equally, and calls are batched so
 * clock_gettime overhead (~21 ns here) is amortised.  We report the minimum over
 * many blocks, which is the statistic most robust to interference from other load
 * on the machine, plus the median.                                                */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include "mkl_dfti.h"
#include "fftw_min.h"
#include "peakfft.h"

static double now(void){ struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
                         return t.tv_sec+1e-9*t.tv_nsec; }
static unsigned long long rs=88172645463325252ULL;
static double u(void){ rs^=rs<<13; rs^=rs>>7; rs^=rs<<17;
                       return (double)(rs>>11)/9007199254740992.0; }
static double gauss(void){ return sqrt(-2.0*log(u()+1e-300))*cos(2.0*M_PI*u()); }
static int cmpd(const void*a,const void*b){ double x=*(const double*)a,y=*(const double*)b;
                                            return x<y?-1:x>y; }

static void bench(size_t N,int K,int blocks,int batch){
  float *in,*out;
  if(posix_memalign((void**)&in,4096,N*8)||posix_memalign((void**)&out,4096,N*8)) exit(1);
  for(size_t i=0;i<N;i++){ in[2*i]=(float)gauss(); in[2*i+1]=(float)gauss(); }

  DFTI_DESCRIPTOR_HANDLE h;
  DftiCreateDescriptor(&h,DFTI_SINGLE,DFTI_COMPLEX,1,(MKL_LONG)N);
  DftiSetValue(h,DFTI_PLACEMENT,DFTI_NOT_INPLACE);
  DftiCommitDescriptor(h);

  fftwf_import_wisdom_from_filename("fftw.wisdom");
  fftwf_complex *fi=fftwf_alloc_complex(N),*fo=fftwf_alloc_complex(N);
  fftwf_plan fp=fftwf_plan_dft_1d((int)N,fi,fo,FFTW_FORWARD,FFTW_PATIENT);
  fftwf_export_wisdom_to_filename("fftw.wisdom");
  memcpy(fi,in,N*8);

  pf_plan *p=pf_create(N);
  int idx[PF_MAX_K]; float re[PF_MAX_K],im[PF_MAX_K];

  double *tk=malloc(blocks*sizeof(double)), *tf=malloc(blocks*sizeof(double));
  double *te=malloc(blocks*sizeof(double)), *tt=malloc(blocks*sizeof(double));
  for(int w=0;w<3;w++){ DftiComputeForward(h,in,out); fftwf_execute(fp);
                        pf_fft(p,in,out); pf_topk(p,in,K,idx,re,im); }
  for(int b=0;b<blocks;b++){
    double t0=now(); for(int q=0;q<batch;q++) DftiComputeForward(h,in,out);  tk[b]=(now()-t0)/batch;
    t0=now();        for(int q=0;q<batch;q++) fftwf_execute(fp);             tf[b]=(now()-t0)/batch;
    t0=now();        for(int q=0;q<batch;q++) pf_fft(p,in,out);              te[b]=(now()-t0)/batch;
    t0=now();        for(int q=0;q<batch;q++) pf_topk(p,in,K,idx,re,im);     tt[b]=(now()-t0)/batch;
  }
  qsort(tk,blocks,sizeof(double),cmpd); qsort(tf,blocks,sizeof(double),cmpd);
  qsort(te,blocks,sizeof(double),cmpd); qsort(tt,blocks,sizeof(double),cmpd);
  printf("2^%-7d %9.2fus %9.2fus %9.2fus %9.2fus %7.2fx %7.2fx\n",
         (int)lround(log2((double)N)), tk[0]*1e6, tf[0]*1e6, te[0]*1e6, tt[0]*1e6,
         tk[0]/te[0], tk[0]/tt[0]);
  { const char *csv=getenv("PF_CSV");
    if(csv){ FILE*f=fopen(csv,"a");
      fprintf(f,"%zu,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g\n",N,
        tk[0],tk[blocks/2],tf[0],tf[blocks/2],te[0],te[blocks/2],tt[0],tt[blocks/2]);
      fclose(f);} }
  pf_destroy(p); free(in); free(out);
}

int main(int argc,char**argv){
  int K = argc>1 ? atoi(argv[1]) : 8;
  const char *csv = getenv("PF_CSV");
  if(csv){ FILE*f=fopen(csv,"w"); fprintf(f,"N,mkl_min,mkl_med,fftw_min,fftw_med,fft_min,fft_med,topk_min,topk_med\n"); fclose(f); }
  printf("peakfft benchmark - single threaded, complex-to-complex, float32   (K = %d)\n",K);
  printf("%-9s %10s %10s %10s %10s %8s %8s\n","N","MKL","FFTW","pf_fft","pf_topk","fft/MKL","topk/MKL");
  bench(1024,K,200,200);
  for(int lg=12; lg<=20; lg++){
    size_t N=(size_t)1<<lg;
    int batch = N<=(1u<<15) ? 50 : (N<=(1u<<18) ? 5 : 1);
    int blocks = N<=(1u<<15) ? 60 : (N<=(1u<<18) ? 40 : 25);
    bench(N,K,blocks,batch);
  }
  return 0;
}
