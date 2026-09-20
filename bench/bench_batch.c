/* Batched comparison: MKL, stock FFTW, amd-fftw (AOCL), peakfft.
 *
 * Every library gets the batch, not just peakfft - MKL through
 * DFTI_NUMBER_OF_TRANSFORMS, both FFTWs through fftwf_plan_many_dft.  Batching
 * speeds all of them up (shared twiddle tables stay hot, plan overhead
 * amortises), so comparing a batched peakfft against unbatched baselines would
 * be meaningless.
 *
 * As elsewhere, all four run in one process interleaved per timed block,
 * because machine load here drifts by 2x over minutes.
 *
 * peakfft is measured twice: plain top-K, and top-K with the detection floor.
 * The baselines produce a full spectrum, which is the work a caller would still
 * have to scan; that asymmetry is the point of the exercise. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <dlfcn.h>
#include "mkl_dfti.h"
#include "fftw_min.h"
#include "peakfft.h"

static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+1e-9*t.tv_nsec;}
static unsigned long long rs=88172645463325252ULL;
static double u(void){rs^=rs<<13;rs^=rs>>7;rs^=rs<<17;return (double)(rs>>11)/9007199254740992.0;}
static double gauss(void){return sqrt(-2.0*log(u()+1e-300))*cos(2.0*M_PI*u());}
static int cmpd(const void*a,const void*b){double x=*(const double*)a,y=*(const double*)b;return x<y?-1:x>y;}
static int cmpdd(const void*a,const void*b){double x=*(const double*)a,y=*(const double*)b;return x<y?1:(x>y?-1:0);}

static void*(*s_malloc)(size_t); static void(*s_free)(void*);
static fftwf_plan(*s_many)(int,const int*,int,fftwf_complex*,const int*,int,int,
                           fftwf_complex*,const int*,int,int,int,unsigned);
static void(*s_exec)(fftwf_plan);
static int(*s_imp)(const char*); static int(*s_exp)(const char*);

static void bench(size_t N,int B,int K,int blocks,int reps){
  const size_t NB=N*(size_t)B;
  float *in,*out;
  if(posix_memalign((void**)&in,4096,NB*8)||posix_memalign((void**)&out,4096,NB*8)) exit(1);
  for(size_t i=0;i<NB;i++){ in[2*i]=(float)gauss(); in[2*i+1]=(float)gauss(); }

  MKL_LONG nn=(MKL_LONG)N;
  DFTI_DESCRIPTOR_HANDLE h;
  DftiCreateDescriptor(&h,DFTI_SINGLE,DFTI_COMPLEX,1,nn);
  DftiSetValue(h,DFTI_PLACEMENT,DFTI_NOT_INPLACE);
  DftiSetValue(h,DFTI_NUMBER_OF_TRANSFORMS,(MKL_LONG)B);
  DftiSetValue(h,DFTI_INPUT_DISTANCE,nn);
  DftiSetValue(h,DFTI_OUTPUT_DISTANCE,nn);
  DftiCommitDescriptor(h);

  int nd=(int)N;
  /* PATIENT times candidate plans on the whole batch, which is hours at 2^20x128.
     The sub-plans are the same ones the single-transform runs already explored, so
     seed from that wisdom and use MEASURE once the batch itself is large. */
  const unsigned FLAGS = (N*(size_t)B<=(1u<<22)) ? FFTW_PATIENT : FFTW_MEASURE;
  char wf[64]; snprintf(wf,sizeof wf,"amdfftw.b%d.wisdom",B);
  fftwf_import_wisdom_from_filename("amdfftw.wisdom");
  fftwf_import_wisdom_from_filename(wf);
  fftwf_complex *ai=fftwf_alloc_complex(NB),*ao=fftwf_alloc_complex(NB);
  fftwf_plan ap=fftwf_plan_many_dft(1,&nd,B,ai,NULL,1,nd,ao,NULL,1,nd,
                                    FFTW_FORWARD,FLAGS);
  if(!getenv("PF_WISDOM_RO")) fftwf_export_wisdom_to_filename(wf);
  memcpy(ai,in,NB*8);

  char sf[64]; snprintf(sf,sizeof sf,"sysfftw.b%d.wisdom",B);
  if(s_imp){ s_imp("sysfftw.wisdom"); s_imp(sf); }
  fftwf_complex *si=s_malloc(sizeof(fftwf_complex)*NB),*so=s_malloc(sizeof(fftwf_complex)*NB);
  fftwf_plan sp=s_many(1,&nd,B,si,NULL,1,nd,so,NULL,1,nd,FFTW_FORWARD,FLAGS);
  if(s_exp && !getenv("PF_WISDOM_RO")) s_exp(sf);
  memcpy(si,in,NB*8);

  pf_plan *p=pf_create(N);
  pf_peak *pk=malloc((size_t)B*K*sizeof(pf_peak));
  int *cnt=malloc((size_t)B*sizeof(int));

  /* Accuracy and the detection floor, both from MKL's own output on this data. */
  DftiComputeForward(h,in,out);
  double *mag=malloc(N*sizeof(double)),*srt=malloc(N*sizeof(double));
  for(size_t k=0;k<N;k++) mag[k]=hypot(out[2*k],out[2*k+1]);
  memcpy(srt,mag,N*sizeof(double)); qsort(srt,N,sizeof(double),cmpdd);
  float T=(float)(0.5*(srt[N/1000]+srt[N/1000+1]));   /* ~1 crossing per 1000 bins */
  int *ord=malloc(N*sizeof(int));
  for(size_t k=0;k<N;k++) ord[k]=(int)k;
  for(int a=0;a<K;a++){ int b=a;
    for(size_t c=a+1;c<N;c++) if(mag[ord[c]]>mag[ord[b]]) b=(int)c;
    int t=ord[a];ord[a]=ord[b];ord[b]=t; }
  pf_topk_many(p,in,N,B,K,0.f,pk,cnt,PF_FORWARD,0,N);
  int idxbad=0; double relerr=0;
  for(int a=0;a<cnt[0];a++){
    if(pk[a].index!=ord[a]) idxbad++;
    double d=hypot(pk[a].re-out[2*pk[a].index],pk[a].im-out[2*pk[a].index+1]);
    if(mag[pk[a].index]>0 && d/mag[pk[a].index]>relerr) relerr=d/mag[pk[a].index];
  }
  /* threshold mode must not lose a peak that plain top-K found above the floor */
  int nthr=pf_topk_many(p,in,N,B,K,T,pk,cnt,PF_FORWARD,0,N);
  int expthr=0; for(int a=0;a<K;a++) if(srt[a]>(double)T) expthr++;
  int thrbad = (cnt[0]!=expthr);
  (void)nthr;
  free(mag);free(srt);free(ord);

  double *tk=malloc(blocks*8),*ts=malloc(blocks*8),*ta=malloc(blocks*8),
         *tp=malloc(blocks*8),*tt=malloc(blocks*8);
  for(int w=0;w<2;w++){ DftiComputeForward(h,in,out); s_exec(sp); fftwf_execute(ap);
    pf_topk_many(p,in,N,B,K,0.f,pk,cnt,PF_FORWARD,0,N); }
  for(int b=0;b<blocks;b++){
    double t0;
    t0=now(); for(int q=0;q<reps;q++) DftiComputeForward(h,in,out);          tk[b]=(now()-t0)/reps/B;
    t0=now(); for(int q=0;q<reps;q++) s_exec(sp);                            ts[b]=(now()-t0)/reps/B;
    t0=now(); for(int q=0;q<reps;q++) fftwf_execute(ap);                     ta[b]=(now()-t0)/reps/B;
    t0=now(); for(int q=0;q<reps;q++) pf_topk_many(p,in,N,B,K,0.f,pk,cnt,PF_FORWARD,0,N);
                                                                             tp[b]=(now()-t0)/reps/B;
    t0=now(); for(int q=0;q<reps;q++) pf_topk_many(p,in,N,B,K,T,pk,cnt,PF_FORWARD,0,N);
                                                                             tt[b]=(now()-t0)/reps/B;
  }
  qsort(tk,blocks,8,cmpd);qsort(ts,blocks,8,cmpd);qsort(ta,blocks,8,cmpd);
  qsort(tp,blocks,8,cmpd);qsort(tt,blocks,8,cmpd);
  double best=tp[0]<tt[0]?tp[0]:tt[0];
  printf("2^%-3d %4d %8.2f %8.2f %8.2f %8.2f %8.2f  %6.2fx %6.2fx %6.2fx  %8.1e %s%s\n",
    (int)lround(log2((double)N)),B,tk[0]*1e6,ts[0]*1e6,ta[0]*1e6,tp[0]*1e6,tt[0]*1e6,
    tk[0]/best,ts[0]/best,ta[0]/best,relerr,
    idxbad?"IDX-BAD ":"idx ok",thrbad?" THR-BAD":"");
  const char*csv=getenv("PF_CSV");
  if(csv){FILE*f=fopen(csv,"a");
    fprintf(f,"%zu,%d,%.9g,%.9g,%.9g,%.9g,%.9g,%.3e,%d\n",N,B,tk[0],ts[0],ta[0],tp[0],tt[0],relerr,idxbad);
    fclose(f);}
  free(tk);free(ts);free(ta);free(tp);free(tt);free(pk);free(cnt);
  pf_destroy(p); DftiFreeDescriptor(&h); free(in); free(out);
}

int main(int argc,char**argv){
  int K=argc>1?atoi(argv[1]):8;
  void *lib=dlopen("libfftw3f.so.3",RTLD_NOW|RTLD_LOCAL|RTLD_DEEPBIND);
  if(!lib){ fprintf(stderr,"dlopen stock fftw failed: %s\n",dlerror()); return 1; }
  s_malloc=dlsym(lib,"fftwf_malloc"); s_free=dlsym(lib,"fftwf_free");
  s_many=dlsym(lib,"fftwf_plan_many_dft"); s_exec=dlsym(lib,"fftwf_execute");
  s_imp=dlsym(lib,"fftwf_import_wisdom_from_filename");
  s_exp=dlsym(lib,"fftwf_export_wisdom_to_filename");
  if(!s_malloc||!s_many||!s_exec){ fprintf(stderr,"dlsym failed\n"); return 1; }
  (void)s_free;
  { Dl_info di;
    if(dladdr((void*)s_exec,&di)&&di.dli_fname) printf("stock FFTW -> %s\n",di.dli_fname);
    if(dladdr((void*)fftwf_execute,&di)&&di.dli_fname) printf("amd   FFTW -> %s\n",di.dli_fname); }
  const char*csv=getenv("PF_CSV");
  if(csv){FILE*f=fopen(csv,"w");fprintf(f,"N,B,mkl,sysfftw,amdfftw,peakfft,peakfft_thr,relerr,idxbad\n");fclose(f);}
  printf("batched, all four in one process, us per transform   (K=%d, backend=%s)\n",K,pf_isa());
  printf("%-5s %4s %8s %8s %8s %8s %8s  %7s %7s %7s  %8s %s\n",
    "N","B","MKL","FFTW","amdFFTW","pf topK","pf +thr","vs MKL","vs FFTW","vs AMD","rel err","check");
  const int Bs[]={16,32,64,128};
  const int lgs[]={10,12,14,16,18,20};
  for(unsigned i=0;i<sizeof(lgs)/sizeof(*lgs);i++){
    size_t N=(size_t)1<<lgs[i];
    for(unsigned j=0;j<4;j++){
      int B=Bs[j];
      size_t work=N*(size_t)B;
      int reps  = work<=(1u<<20)?20:(work<=(1u<<23)?4:1);
      int blocks= work<=(1u<<20)?30:(work<=(1u<<23)?20:10);
      bench(N,B,K,blocks,reps);
    }
    printf("\n");
  }
  return 0;
}
