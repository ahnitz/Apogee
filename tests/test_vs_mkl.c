/* Independent cross-check of apogee against Intel MKL's DFTI.
   Optional - built only when MKLINC/MKLLIB are supplied:
     make test-mkl MKLINC=/path/include MKLLIB=/path/lib
   This is the test that actually bounds the error introduced by the reduced-precision
   intermediate, since test_topk only proves ap_topk agrees with ap_fft.            */
#include <string.h>
#include "mkl_dfti.h"
#include "apogee.h"
#include "testutil.h"

typedef struct { double m; int i; } rank_t;
static int cmp_rank(const void*a,const void*b){
  double x=((const rank_t*)a)->m,y=((const rank_t*)b)->m; return x<y?1:x>y?-1:0; }

static void run(size_t N,int K,int trials,int sign){
  float *in=ap_alloc(N*8), *mkl=ap_alloc(N*8), *mine=ap_alloc(N*8);
  rank_t *r=malloc(sizeof(rank_t)*N);
  DFTI_DESCRIPTOR_HANDLE h;
  DftiCreateDescriptor(&h,DFTI_SINGLE,DFTI_COMPLEX,1,(MKL_LONG)N);
  DftiSetValue(h,DFTI_PLACEMENT,DFTI_NOT_INPLACE);
  DftiCommitDescriptor(h);
  ap_plan *p=ap_create(N);
  ap_peak pk[AP_MAX_K];
  double worst_fft=0, worst_topk=0; int set_bad=0, order_bad=0;
  for(int t=0;t<trials;t++){
    ap_seed(0xDEADBEEFu*(t+1)+N);
    for(size_t n=0;n<N;n++){ in[2*n]=(float)ap_gauss(); in[2*n+1]=(float)ap_gauss(); }
    if(sign==AP_FORWARD) DftiComputeForward(h,in,mkl); else DftiComputeBackward(h,in,mkl);
    for(size_t k=0;k<N;k++){ r[k].m=(double)mkl[2*k]*mkl[2*k]+(double)mkl[2*k+1]*mkl[2*k+1];
                             r[k].i=(int)k; }
    qsort(r,N,sizeof(rank_t),cmp_rank);
    double peak=sqrt(r[0].m);

    ap_fft(p,in,mine,sign);
    for(size_t k=0;k<N;k++){
      double d=hypot(mine[2*k]-mkl[2*k],mine[2*k+1]-mkl[2*k+1]);
      if(d/peak>worst_fft) worst_fft=d/peak;
    }
    int n=ap_topk(p,in,K,pk,sign);
    CHECK(n==K,"ap_topk returned %d expected %d",n,K);
    for(int a=0;a<K;a++){
      int found=0; for(int b=0;b<K;b++) if(pk[a].index==r[b].i) found=1;
      if(!found) set_bad++;
      if(pk[a].index!=r[a].i) order_bad++;
      double d=hypot(pk[a].re-mkl[2*pk[a].index], pk[a].im-mkl[2*pk[a].index+1]);
      if(d/sqrt(r[a].m)>worst_topk) worst_topk=d/sqrt(r[a].m);
    }
  }
  printf("  N=%-8zu K=%-3d x%-3d %-8s ap_fft max rel %.3e | ap_topk set_err=%d order_err=%d max rel %.3e\n",
         N,K,trials,sign==AP_FORWARD?"fwd":"bwd",worst_fft,set_bad,order_bad,worst_topk);
  CHECK_LE(worst_fft,1e-5,"N=%zu ap_fft vs MKL",N);
  CHECK(set_bad==0,"N=%zu top-K set disagrees with MKL in %d slots",N,set_bad);
  CHECK(order_bad==0,"N=%zu top-K order disagrees with MKL in %d slots",N,order_bad);
  CHECK_LE(worst_topk,1e-5,"N=%zu ap_topk values vs MKL",N);
  DftiFreeDescriptor(&h); ap_destroy(p); free(in); free(mkl); free(mine); free(r);
}

int main(void){
  printf("apogee vs MKL (tolerance 1e-5 relative)\n");
  for(int d=0;d<2;d++){
    int sg = d? AP_BACKWARD : AP_FORWARD;
    run(1024,8,30,sg);
    for(int lg=12; lg<=19; lg++) run((size_t)1<<lg,8,5,sg);
    run(1048576,8,6,sg);
    run(1048576,1,6,sg);
    run(1048576,AP_MAX_K,3,sg);
  }
  return ap_report("test_vs_mkl");
}
