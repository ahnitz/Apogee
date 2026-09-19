/* Independent cross-check of peakfft against Intel MKL's DFTI.
   Optional - built only when MKLINC/MKLLIB are supplied:
     make test-mkl MKLINC=/path/include MKLLIB=/path/lib
   This is the test that actually bounds the error introduced by the reduced-precision
   intermediate, since test_topk only proves pf_topk agrees with pf_fft.            */
#include <string.h>
#include "mkl_dfti.h"
#include "peakfft.h"
#include "testutil.h"

typedef struct { double m; int i; } rank_t;
static int cmp_rank(const void*a,const void*b){
  double x=((const rank_t*)a)->m,y=((const rank_t*)b)->m; return x<y?1:x>y?-1:0; }

static void run(size_t N,int K,int trials){
  float *in=pf_alloc(N*8), *mkl=pf_alloc(N*8), *mine=pf_alloc(N*8);
  rank_t *r=malloc(sizeof(rank_t)*N);
  DFTI_DESCRIPTOR_HANDLE h;
  DftiCreateDescriptor(&h,DFTI_SINGLE,DFTI_COMPLEX,1,(MKL_LONG)N);
  DftiSetValue(h,DFTI_PLACEMENT,DFTI_NOT_INPLACE);
  DftiCommitDescriptor(h);
  pf_plan *p=pf_create(N);
  int idx[PF_MAX_K]; float re[PF_MAX_K], im[PF_MAX_K];
  double worst_fft=0, worst_topk=0; int set_bad=0, order_bad=0;
  for(int t=0;t<trials;t++){
    pf_seed(0xDEADBEEFu*(t+1)+N);
    for(size_t n=0;n<N;n++){ in[2*n]=(float)pf_gauss(); in[2*n+1]=(float)pf_gauss(); }
    DftiComputeForward(h,in,mkl);
    for(size_t k=0;k<N;k++){ r[k].m=(double)mkl[2*k]*mkl[2*k]+(double)mkl[2*k+1]*mkl[2*k+1];
                             r[k].i=(int)k; }
    qsort(r,N,sizeof(rank_t),cmp_rank);
    double peak=sqrt(r[0].m);

    pf_fft(p,in,mine);
    for(size_t k=0;k<N;k++){
      double d=hypot(mine[2*k]-mkl[2*k],mine[2*k+1]-mkl[2*k+1]);
      if(d/peak>worst_fft) worst_fft=d/peak;
    }
    int n=pf_topk(p,in,K,idx,re,im);
    CHECK(n==K,"pf_topk returned %d expected %d",n,K);
    for(int a=0;a<K;a++){
      int found=0; for(int b=0;b<K;b++) if(idx[a]==r[b].i) found=1;
      if(!found) set_bad++;
      if(idx[a]!=r[a].i) order_bad++;
      double d=hypot(re[a]-mkl[2*idx[a]], im[a]-mkl[2*idx[a]+1]);
      if(d/sqrt(r[a].m)>worst_topk) worst_topk=d/sqrt(r[a].m);
    }
  }
  printf("  N=%-8zu K=%-3d x%-3d  pf_fft max rel %.3e | pf_topk set_err=%d order_err=%d max rel %.3e\n",
         N,K,trials,worst_fft,set_bad,order_bad,worst_topk);
  CHECK_LE(worst_fft,1e-5,"N=%zu pf_fft vs MKL",N);
  CHECK(set_bad==0,"N=%zu top-K set disagrees with MKL in %d slots",N,set_bad);
  CHECK(order_bad==0,"N=%zu top-K order disagrees with MKL in %d slots",N,order_bad);
  CHECK_LE(worst_topk,1e-5,"N=%zu pf_topk values vs MKL",N);
  DftiFreeDescriptor(&h); pf_destroy(p); free(in); free(mkl); free(mine); free(r);
}

int main(void){
  printf("peakfft vs MKL (tolerance 1e-5 relative)\n");
  run(1024,8,50);
  run(1024,1,50);
  run(1048576,8,10);
  run(1048576,1,10);
  run(1048576,PF_MAX_K,5);
  return pf_report("test_vs_mkl");
}
