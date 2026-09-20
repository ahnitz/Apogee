/* Batched API: agreement with the single-transform path, and threshold semantics.
 *
 * The threshold gate is the strict one.  Threshold mode primes the internal
 * candidate test, so a bug there shows up as a *missing* peak, not a wrong
 * value - which a value-comparison test would never catch.  So we check
 * exhaustively against a brute-force scan: every bin above the floor that
 * belongs in the top K must appear, and nothing below the floor may. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "peakfft.h"

static int checks=0, fails=0;
#define CK(c,...) do{ checks++; if(!(c)){ fails++; printf("  FAIL "); printf(__VA_ARGS__); printf("\n"); } }while(0)

static unsigned long long rs=88172645463325252ULL;
static double u(void){ rs^=rs<<13; rs^=rs>>7; rs^=rs<<17; return (double)(rs>>11)/9007199254740992.0; }
static double gs(void){ return sqrt(-2.0*log(u()+1e-300))*cos(2*M_PI*u()); }

/* reference magnitudes over the whole spectrum, from the validated full transform */
static void refmag(pf_plan*p,const float*in,float*out,double*mag,size_t N,int sign){
  pf_fft(p,in,out,sign);
  for(size_t k=0;k<N;k++) mag[k]=hypot(out[2*k],out[2*k+1]);
}
static int cmpd(const void*a,const void*b){ double x=*(const double*)a,y=*(const double*)b;
  return x<y?1:(x>y?-1:0); }

static void run(size_t N,int B,int K,int sign,size_t ws,size_t we,int usethr){
  pf_plan *p=pf_create(N); if(!p) return;
  size_t dist=N+((B&1)?7:0);          /* exercise a non-packed stride too */
  float *in=aligned_alloc(64,2*dist*(size_t)B*sizeof(float));
  float *ot=aligned_alloc(64,2*N*sizeof(float));
  double *mg=malloc(N*sizeof(double)), *sorted=malloc(N*sizeof(double));
  pf_peak *pk=malloc((size_t)B*K*sizeof(pf_peak));
  int *cnt=malloc((size_t)B*sizeof(int));
  memset(in,0,2*dist*(size_t)B*sizeof(float));
  for(int b=0;b<B;b++) for(size_t n=0;n<N;n++){
    in[2*(b*dist+n)]=(float)gs(); in[2*(b*dist+n)+1]=(float)gs(); }

  /* threshold placed so ~1 bin per 1000 in the window exceeds it */
  float T=0.f;
  if(usethr){
    refmag(p,in,ot,mg,N,sign);
    size_t nw=we-ws; memcpy(sorted,mg+ws,nw*sizeof(double));
    qsort(sorted,nw,sizeof(double),cmpd);
    size_t q=nw/1000; if(q<1) q=1;
    /* midway between two order statistics: the floor must not coincide with a
       magnitude, or float rounding decides membership and the test is testing
       its own tie-break rather than the library. */
    T=(float)(0.5*(sorted[q]+sorted[q+1]));
  }
  int tot=pf_topk_many(p,in,dist,B,K,T,pk,cnt,sign,ws,we);
  CK(tot>=0,"N=%zu B=%d: pf_topk_many returned %d",N,B,tot);

  int sum=0;
  for(int b=0;b<B;b++){
    refmag(p,in+2*b*dist,ot,mg,N,sign);
    /* brute-force expected set: bins in [ws,we) above T, K loudest */
    size_t nw=we-ws; memcpy(sorted,mg+ws,nw*sizeof(double));
    qsort(sorted,nw,sizeof(double),cmpd);
    int nexp=0; while(nexp<K && (size_t)nexp<nw && sorted[nexp]>(double)T) nexp++;
    CK(cnt[b]==nexp,"N=%zu B=%d b=%d thr=%d: count %d, expected %d",N,B,b,usethr,cnt[b],nexp);
    sum+=cnt[b];
    for(int a=0;a<cnt[b];a++){
      pf_peak *q=&pk[(size_t)b*K+a];
      CK(q->index>=(long)ws && q->index<(long)we,
         "N=%zu b=%d: index %ld outside [%zu,%zu)",N,b,q->index,ws,we);
      CK(q->magnitude>T,"N=%zu b=%d: magnitude %g not above floor %g",N,b,q->magnitude,T);
      /* value must match the reference at that index, and be the a-th loudest */
      double want=mg[q->index];
      CK(fabs(q->magnitude-want)<=1e-5*want+1e-4,
         "N=%zu b=%d a=%d: magnitude %g vs reference %g",N,b,a,q->magnitude,want);
      CK(fabs(want-sorted[a])<=1e-5*want+1e-4,
         "N=%zu b=%d a=%d: rank wrong, got %g expected %g",N,b,a,want,sorted[a]);
      /* complex value, with the sign convention of the requested direction */
      double dr=q->re-ot[2*q->index], di=q->im-ot[2*q->index+1];
      CK(hypot(dr,di)<=1e-5*want+1e-4,"N=%zu b=%d a=%d: complex value off by %g",
         N,b,a,hypot(dr,di));
      if(a) CK(pk[(size_t)b*K+a-1].magnitude>=q->magnitude,
               "N=%zu b=%d: peaks not sorted at a=%d",N,b,a);
    }
    /* no false negatives: nothing in the window above the reported floor was missed */
    double cut = cnt[b]? pk[(size_t)b*K+cnt[b]-1].magnitude : (double)T;
    if(cnt[b]<K){
      int above=0;
      for(size_t k=ws;k<we;k++) if(mg[k]>cut+1e-6*cut) above++;
      CK(above<=cnt[b],"N=%zu b=%d: %d bins above the reported cut but only %d returned",
         N,b,above,cnt[b]);
    }
  }
  CK(tot==sum,"N=%zu B=%d: total %d != sum of counts %d",N,B,tot,sum);

  /* batched must agree exactly with the single-transform entry point */
  if(!usethr){
    pf_peak one[PF_MAX_K];
    for(int b=0;b<B;b++){
      int n=pf_topk_window(p,in+2*b*dist,K,one,sign,ws,we);
      CK(n==cnt[b],"N=%zu b=%d: batched count %d vs single %d",N,b,cnt[b],n);
      for(int a=0;a<n&&a<cnt[b];a++)
        CK(one[a].index==pk[(size_t)b*K+a].index,
           "N=%zu b=%d a=%d: batched index %ld vs single %ld",N,b,a,
           pk[(size_t)b*K+a].index,one[a].index);
    }
  }
  free(in);free(ot);free(mg);free(sorted);free(pk);free(cnt); pf_destroy(p);
}

int main(void){
  if(!pf_supported(1024)){ printf("test_batch: unsupported CPU, skipped\n"); return 0; }
  /* PF_QUICK trims the matrix to something that runs between edits.  It keeps one
     batch size and the two smallest lengths but every mode - threshold, window and
     both directions - because those are where the bugs have actually been. */
  const int quick = getenv("PF_QUICK") != NULL;
  const int Bs_full[]={16,32,64,128}, Bs_quick[]={16};
  const size_t Ns_full[]={1024,4096,16384,65536}, Ns_quick[]={1024,4096};
  const int *Bs = quick?Bs_quick:Bs_full;
  const size_t *Ns = quick?Ns_quick:Ns_full;
  const int nB = quick?1:4, nN = quick?2:4;
  for(int i=0;i<nN;i++){
    size_t N=Ns[i];
    for(int j=0;j<nB;j++){
      int B=Bs[j]; if(N>=65536) B=Bs[j]>32?32:Bs[j];
      int K=(N>=65536)?8:16;
      run(N,B,K,PF_FORWARD,0,N,0);
      run(N,B,K,PF_FORWARD,0,N,1);
      run(N,B,K,PF_BACKWARD,0,N,1);
      run(N,B,K,PF_FORWARD,N/5,(size_t)(N*0.7),1);   /* windowed + threshold */
      run(N,B,K,PF_BACKWARD,N/2,N,0);
    }
  }
  /* K larger than the number of bins above the floor: counts must shrink, not pad */
  run(4096,16,64,PF_FORWARD,0,4096,1);
  printf("test_batch %30s %d checks, %d failures  [%s]\n","",checks,fails,fails?"FAIL":"ok");
  return fails?1:0;
}
