/* Four-way interleaved benchmark: MKL, stock FFTW, amd-fftw (AOCL), peakfft.
 * amd-fftw is linked statically; stock FFTW is dlopen'd and called through
 * pointers, so both live in one process and every competitor sees the same
 * machine state within a timed block.  Machine load here drifts by 2x over
 * minutes, which makes separate runs useless for comparison. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <dlfcn.h>
#include <stddef.h>
#include "mkl_dfti.h"
#include "fftw_min.h"
#include "peakfft.h"

static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+1e-9*t.tv_nsec;}
static unsigned long long rs=88172645463325252ULL;
static double u(void){rs^=rs<<13;rs^=rs>>7;rs^=rs<<17;return (double)(rs>>11)/9007199254740992.0;}
static double gauss(void){return sqrt(-2.0*log(u()+1e-300))*cos(2.0*M_PI*u());}
static int cmpd(const void*a,const void*b){double x=*(const double*)a,y=*(const double*)b;return x<y?-1:x>y;}

/* stock FFTW via dlopen */
static void*(*s_malloc)(size_t);
static fftwf_plan(*s_plan)(int,fftwf_complex*,fftwf_complex*,int,unsigned);
static void(*s_exec)(fftwf_plan);
static int(*s_imp)(const char*); static int(*s_exp)(const char*);

static void bench(size_t N,int K,int blocks,int batch){
  float *in,*out;
  if(posix_memalign((void**)&in,4096,N*8)||posix_memalign((void**)&out,4096,N*8)) exit(1);
  for(size_t i=0;i<N;i++){ in[2*i]=(float)gauss(); in[2*i+1]=(float)gauss(); }
  DFTI_DESCRIPTOR_HANDLE h;
  DftiCreateDescriptor(&h,DFTI_SINGLE,DFTI_COMPLEX,1,(MKL_LONG)N);
  DftiSetValue(h,DFTI_PLACEMENT,DFTI_NOT_INPLACE); DftiCommitDescriptor(h);

  fftwf_import_wisdom_from_filename("amdfftw.wisdom");
  fftwf_complex *ai=fftwf_alloc_complex(N),*ao=fftwf_alloc_complex(N);
  fftwf_plan ap=fftwf_plan_dft_1d((int)N,ai,ao,FFTW_FORWARD,FFTW_PATIENT);
  /* Never persist a plan that was chosen under contention: FFTW_PATIENT picks by
     timing candidates, so planning on a loaded machine stores bad plans that every
     later run then reuses.  Build wisdom quietly once, then run read-only. */
  if(!getenv("PF_WISDOM_RO")) fftwf_export_wisdom_to_filename("amdfftw.wisdom");
  memcpy(ai,in,N*8);

  if(s_imp) s_imp("sysfftw.wisdom");
  fftwf_complex *si=(fftwf_complex*)s_malloc(sizeof(fftwf_complex)*N);
  fftwf_complex *so=(fftwf_complex*)s_malloc(sizeof(fftwf_complex)*N);
  fftwf_plan sp=s_plan((int)N,si,so,FFTW_FORWARD,FFTW_PATIENT);
  if(s_exp && !getenv("PF_WISDOM_RO")) s_exp("sysfftw.wisdom");
  memcpy(si,in,N*8);

  pf_plan *p=pf_create(N); pf_peak pk[PF_MAX_K];

  /* Accuracy on the same data that is about to be timed: top-K indices must match
     MKL's ranking exactly, and the reported values must agree with MKL's. */
  DftiComputeForward(h,in,out);
  double *mag=malloc(N*sizeof(double));
  for(size_t k=0;k<N;k++) mag[k]=(double)out[2*k]*out[2*k]+(double)out[2*k+1]*out[2*k+1];
  int *ord=malloc(N*sizeof(int));
  for(size_t k=0;k<N;k++) ord[k]=(int)k;
  for(int a=0;a<K;a++){ int b=a;
    for(size_t c=a+1;c<N;c++) if(mag[ord[c]]>mag[ord[b]]) b=(int)c;
    int t=ord[a]; ord[a]=ord[b]; ord[b]=t; }
  int nk=pf_topk(p,in,K,pk,PF_FORWARD);
  int idxbad=0; double relerr=0;
  for(int a=0;a<nk;a++){
    if(pk[a].index!=ord[a]) idxbad++;
    double d=hypot(pk[a].re-out[2*pk[a].index], pk[a].im-out[2*pk[a].index+1]);
    double r=d/sqrt(mag[pk[a].index]);
    if(r>relerr) relerr=r;
  }
  free(mag); free(ord);
  double *tk=malloc(blocks*8),*ts=malloc(blocks*8),*ta=malloc(blocks*8),*tp=malloc(blocks*8);
  for(int w=0;w<3;w++){ DftiComputeForward(h,in,out); s_exec(sp); fftwf_execute(ap);
                        pf_topk(p,in,K,pk,PF_FORWARD); }
  for(int b=0;b<blocks;b++){
    double t0=now(); for(int q=0;q<batch;q++) DftiComputeForward(h,in,out); tk[b]=(now()-t0)/batch;
    t0=now();        for(int q=0;q<batch;q++) s_exec(sp);                   ts[b]=(now()-t0)/batch;
    t0=now();        for(int q=0;q<batch;q++) fftwf_execute(ap);            ta[b]=(now()-t0)/batch;
    t0=now();        for(int q=0;q<batch;q++) pf_topk(p,in,K,pk,PF_FORWARD);tp[b]=(now()-t0)/batch;
  }
  qsort(tk,blocks,8,cmpd);qsort(ts,blocks,8,cmpd);qsort(ta,blocks,8,cmpd);qsort(tp,blocks,8,cmpd);
  printf("2^%-5d %9.2f %9.2f %9.2f %9.2f  %6.2fx %6.2fx %6.2fx   %8.1e %s\n",
         (int)lround(log2((double)N)),tk[0]*1e6,ts[0]*1e6,ta[0]*1e6,tp[0]*1e6,
         tk[0]/tp[0], ts[0]/tp[0], ta[0]/tp[0], relerr, idxbad?"IDX-MISMATCH":"idx ok");
  const char*csv=getenv("PF_CSV");
  if(csv){FILE*f=fopen(csv,"a");fprintf(f,"%zu,%.9g,%.9g,%.9g,%.9g,%.3e,%d\n",N,tk[0],ts[0],ta[0],tp[0],relerr,idxbad);fclose(f);}
  pf_destroy(p); free(in); free(out);
}

int main(int argc,char**argv){
  int K=argc>1?atoi(argv[1]):8;
  void *lib=dlopen("libfftw3f.so.3",RTLD_NOW|RTLD_LOCAL|RTLD_DEEPBIND);
  if(!lib){ fprintf(stderr,"dlopen stock fftw failed: %s\n",dlerror()); return 1; }
  s_malloc=dlsym(lib,"fftwf_malloc"); s_plan=dlsym(lib,"fftwf_plan_dft_1d");
  s_exec=dlsym(lib,"fftwf_execute");
  s_imp=dlsym(lib,"fftwf_import_wisdom_from_filename");
  s_exp=dlsym(lib,"fftwf_export_wisdom_to_filename");
  if(!s_malloc||!s_plan||!s_exec){ fprintf(stderr,"dlsym failed\n"); return 1; }
  const char*csv=getenv("PF_CSV");
  if(csv){FILE*f=fopen(csv,"w");fprintf(f,"N,mkl,sysfftw,amdfftw,peakfft,relerr,idxbad\n");fclose(f);}
  /* MKL exports its own fftwf_* wrapper symbols.  If FFTW is linked normally and
     MKL comes first on the link line, every fftwf_ call silently binds to MKL and
     the "FFTW" column is really a second MKL column.  Resolve FFTW through
     RTLD_DEEPBIND and report where each symbol actually came from. */
  { Dl_info di;
    if(dladdr((void*)s_exec,&di) && di.dli_fname)
      printf("stock FFTW  fftwf_execute -> %s\n",di.dli_fname);
    if(dladdr((void*)fftwf_execute,&di) && di.dli_fname)
      printf("amd   FFTW  fftwf_execute -> %s\n",di.dli_fname);
  }
  printf("all four in one process, interleaved per timed block   (K=%d, backend=%s)\n",K,pf_isa());
  printf("%-7s %9s %9s %9s %9s  %7s %7s %7s   %8s %s\n","N","MKL","FFTW","amdFFTW","pf_topk",
         "vs MKL","vs FFTW","vs AMD","rel err","top-K indices");
  bench(1024,K,200,200);
  for(int lg=12;lg<=20;lg++){ size_t N=(size_t)1<<lg;
    int batch=N<=(1u<<15)?50:(N<=(1u<<18)?5:1);
    int blocks=N<=(1u<<15)?60:(N<=(1u<<18)?40:25);
    bench(N,K,blocks,batch); }
  return 0;
}
