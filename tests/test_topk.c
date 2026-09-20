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

/* Windowed search: peaks must match a brute-force ranking restricted to the same
   window, for windows of every shape - full, aligned, ragged, tiny, and one that
   deliberately excludes the global maximum (which is what breaks a scan whose
   threshold was primed from the global max). */
static void run_window(size_t N,int K,int trials){
  float *in=pf_alloc(N*8), *out=pf_alloc(N*8);
  rank_t *r=malloc(sizeof(rank_t)*N);
  pf_plan *p=pf_create(N);
  pf_peak pk[PF_MAX_K];
  int bad=0, checks=0;
  for(int t=0;t<trials;t++){
    fill(in,N,t%4,0x5DEECE66DULL*(t+3)+N);
    pf_fft(p,in,out,PF_FORWARD);
    for(size_t k=0;k<N;k++){ r[k].m=(double)out[2*k]*out[2*k]+(double)out[2*k+1]*out[2*k+1];
                             r[k].i=(int)k; }
    qsort(r,N,sizeof(rank_t),cmp_rank);
    size_t gmax=(size_t)r[0].i;
    size_t wins[8][2];
    wins[0][0]=0;           wins[0][1]=N;                    /* full            */
    wins[1][0]=N/4;         wins[1][1]=N/4+N/2;              /* middle 50%      */
    wins[2][0]=N/3+7;       wins[2][1]=N/3+7+(2*N)/3-11;     /* ragged 67%      */
    wins[3][0]=0;           wins[3][1]=N/2;                  /* leading half    */
    wins[4][0]=N/2;         wins[4][1]=N;                    /* trailing half   */
    wins[5][0]=gmax+1;      wins[5][1]=N;                    /* excludes argmax */
    wins[6][0]=N-3;         wins[6][1]=N;                    /* tiny, at end    */
    wins[7][0]=gmax;        wins[7][1]=gmax+1;               /* exactly argmax  */
    for(int w=0;w<8;w++){
      size_t s=wins[w][0], e=wins[w][1];
      if(s>=e || e>N) continue;
      int n=pf_topk_window(p,in,K,pk,PF_FORWARD,s,e);
      /* brute force over the same window */
      int m=0;
      for(size_t k=0;k<N;k++) if((size_t)r[k].i>=s && (size_t)r[k].i<e) { if(m<K) r[m++]=r[k]; }
      int want = (int)((e-s) < (size_t)K ? (e-s) : (size_t)K);
      checks++;
      if(n!=want){ bad++; printf("  FAIL N=%zu win[%zu,%zu) returned %d want %d\n",N,s,e,n,want); continue; }
      for(int a=0;a<n;a++){
        if((size_t)pk[a].index< s || (size_t)pk[a].index>=e){
          bad++; printf("  FAIL N=%zu win[%zu,%zu) idx %ld outside\n",N,s,e,pk[a].index); break; }
      }
      /* rebuild the in-window ranking cleanly and compare */
      for(size_t k=0;k<N;k++){ r[k].m=(double)out[2*k]*out[2*k]+(double)out[2*k+1]*out[2*k+1];
                               r[k].i=(int)k; }
      qsort(r,N,sizeof(rank_t),cmp_rank);
      int seen=0;
      for(size_t k=0;k<N && seen<n;k++){
        if((size_t)r[k].i<s||(size_t)r[k].i>=e) continue;
        if(pk[seen].index!=r[k].i){
          bad++; printf("  FAIL N=%zu win[%zu,%zu) rank %d: got %ld want %d\n",
                        N,s,e,seen,pk[seen].index,r[k].i); break; }
        seen++;
      }
    }
  }
  printf("  N=%-8zu K=%-3d x%-3d windows: %d checks, %d failures\n",N,K,trials,checks,bad);
  CHECK(bad==0,"N=%zu windowed top-K disagrees with brute force in %d cases",N,bad);
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
  printf("windowed search\n");
  run_window(1024,8,6);
  run_window(4096,8,4);
  run_window(1<<14,8,3);
  run_window(1<<16,4,2);
  run_window(1<<18,4,2);
  run_window(1<<20,4,1);
  run_window(1024,1,6);
  return pf_report("test_topk");
}
