/* peakfft top-K validation.
   pf_topk is checked against a brute-force ranking of pf_fft's own output, over
   many random trials and several signal shapes.  pf_fft is itself validated
   against a double-precision reference DFT in test_units. */
#include <string.h>
#include "peakfft.h"
#include "testutil.h"

typedef struct { double m; int i; } rank_t;
static int cmp_rank(const void *a,const void *b){
  double x=((const rank_t*)a)->m, y=((const rank_t*)b)->m;
  return x<y ? 1 : x>y ? -1 : 0;
}

/* mode 0: complex white noise (the design target - peak is a ~5 sigma fluctuation)
   mode 1: noise plus one strong tone
   mode 2: noise plus several tones
   mode 3: noise with a deliberate near-tie pair near the top                     */
static void fill(float *in,size_t N,int mode,unsigned long long seed){
  pf_seed(seed);
  for(size_t n=0;n<N;n++){ in[2*n]=(float)pf_gauss(); in[2*n+1]=(float)pf_gauss(); }
  if(mode==1||mode==3){
    double f=floor(pf_u()*N), A=8.0;
    for(size_t n=0;n<N;n++){ double a=2.0*M_PI*f*n/N;
      in[2*n]+=(float)(A*cos(a)); in[2*n+1]+=(float)(A*sin(a)); }
    if(mode==3){ /* a second tone of almost exactly the same amplitude */
      double f2=fmod(f+N/3,(double)N), A2=A*(1.0+1e-7);
      for(size_t n=0;n<N;n++){ double a=2.0*M_PI*f2*n/N;
        in[2*n]+=(float)(A2*cos(a)); in[2*n+1]+=(float)(A2*sin(a)); }
    }
  }
  if(mode==2) for(int t=0;t<5;t++){
    double f=floor(pf_u()*N), A=2.0+6.0*pf_u();
    for(size_t n=0;n<N;n++){ double a=2.0*M_PI*f*n/N;
      in[2*n]+=(float)(A*cos(a)); in[2*n+1]+=(float)(A*sin(a)); }
  }
}

static void run(size_t N,int K,int trials,int mode,double tol){
  float *in=pf_alloc(N*8), *out=pf_alloc(N*8);
  rank_t *r=malloc(sizeof(rank_t)*N);
  pf_plan *p=pf_create(N);
  pf_peak pk[PF_MAX_K];
  int set_bad=0, order_bad=0; double worst_rel=0;
  for(int t=0;t<trials;t++){
    fill(in,N,mode,0x9E3779B97F4A7C15ULL*(t+1)+mode*7919u+N);
    pf_fft(p,in,out,PF_FORWARD);
    for(size_t k=0;k<N;k++){ r[k].m=(double)out[2*k]*out[2*k]+(double)out[2*k+1]*out[2*k+1];
                             r[k].i=(int)k; }
    qsort(r,N,sizeof(rank_t),cmp_rank);
    int n=pf_topk(p,in,K,pk,PF_FORWARD);
    CHECK(n==K,"pf_topk returned %d, expected %d",n,K);
    double peak=sqrt(r[0].m);
    for(int a=0;a<K;a++){
      int found=0; for(int b=0;b<K;b++) if(pk[a].index==r[b].i) found=1;
      if(!found) set_bad++;
      if(pk[a].index!=r[a].i) order_bad++;
      double d=hypot(pk[a].re-out[2*pk[a].index], pk[a].im-out[2*pk[a].index+1]);
      double rel=d/sqrt(r[a].m);
      if(rel>worst_rel) worst_rel=rel;
      (void)peak;
    }
  }
  const char *mn[]={"white noise","noise+tone","noise+5 tones","noise+near-tie"};
  printf("  N=%-8zu K=%-3d x%-3d %-15s set_err=%-3d order_err=%-3d worst_rel=%.3e\n",
         N,K,trials,mn[mode],set_bad,order_bad,worst_rel);
  CHECK(set_bad==0,"N=%zu K=%d mode=%d: %d bins missing from the true top-K",N,K,mode,set_bad);
  CHECK(order_bad==0,"N=%zu K=%d mode=%d: %d bins out of rank order",N,K,mode,order_bad);
  CHECK_LE(worst_rel,tol,"N=%zu K=%d mode=%d relative value error",N,K,mode);
  pf_destroy(p); free(in); free(out); free(r);
}

int main(void){
  printf("peakfft top-K validation (tolerance 1e-5 relative)\n");
  for(int mode=0;mode<4;mode++) run(1024,8,40,mode,1e-5);
  run(1024,1,40,0,1e-5);
  run(1024,PF_MAX_K,20,0,1e-5);
  for(int lg=12; lg<=19; lg++){ size_t N=(size_t)1<<lg; run(N,8,4,0,1e-5); run(N,1,4,1,1e-5); }
  for(int mode=0;mode<4;mode++) run(1048576,8,6,mode,1e-5);
  run(1048576,1,8,0,1e-5);
  run(1048576,PF_MAX_K,4,0,1e-5);
  return pf_report("test_topk");
}
