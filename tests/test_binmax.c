/* Binned maximum against a brute-force scan of the validated full transform.
 *
 * The dense layout is the thing to get wrong: bin j must stay at slot j even
 * when it has no crossing, or a caller indexing by frequency silently reads a
 * neighbour's peak.  So every bin is checked, including the empty ones, and the
 * ragged last bin is exercised by using window lengths that are not multiples of
 * the bin size. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "apogee.h"
#include "transform.h"

static int checks=0, fails=0;
#define CK(c,...) do{ checks++; if(!(c)){ fails++; printf("  FAIL "); printf(__VA_ARGS__); printf("\n"); } }while(0)

static unsigned long long rs=88172645463325252ULL;
static double u(void){ rs^=rs<<13; rs^=rs>>7; rs^=rs<<17; return (double)(rs>>11)/9007199254740992.0; }
static double gs(void){ return sqrt(-2.0*log(u()+1e-300))*cos(2*M_PI*u()); }
static int cmpdd(const void*a,const void*b){double x=*(const double*)a,y=*(const double*)b;return x<y?1:(x>y?-1:0);}

static void run(size_t N,int B,size_t binsize,int sign,size_t ws,size_t we,int usethr){
  ap_plan *p=ap_create(N); if(!p) return;
  size_t dist=N;
  float *in=aligned_alloc(64,2*dist*(size_t)B*sizeof(float));
  float *ot=aligned_alloc(64,2*N*sizeof(float));
  double *mg=malloc(N*sizeof(double)),*srt=malloc(N*sizeof(double));
  for(int b=0;b<B;b++) for(size_t n=0;n<N;n++){
    in[2*(b*dist+n)]=(float)gs(); in[2*(b*dist+n)+1]=(float)gs(); }

  size_t nb=ap_nbins(p,binsize,ws,we);
  CK(nb==(we-ws+binsize-1)/binsize,"N=%zu: ap_nbins %zu",N,nb);
  ap_peak *pk=malloc((size_t)B*nb*sizeof(ap_peak));
  int *cnt=malloc((size_t)B*sizeof(int));

  float T=0.f;
  if(usethr){
    ap_fft(p,in,ot,sign);
    for(size_t k=0;k<N;k++) mg[k]=hypot(ot[2*k],ot[2*k+1]);
    memcpy(srt,mg+ws,(we-ws)*sizeof(double));
    qsort(srt,we-ws,sizeof(double),cmpdd);
    size_t q=(we-ws)/1000; if(q<1) q=1;
    T=(float)(0.5*(srt[q]+srt[q+1]));
  }
  int tot=ap_binmax(p,in,dist,B,binsize,T,pk,cnt,sign,ws,we);
  CK(tot>=0,"N=%zu binsize=%zu: ap_binmax returned %d",N,binsize,tot);

  int sum=0;
  for(int b=0;b<B;b++){
    ap_fft(p,in+2*b*dist,ot,sign);
    for(size_t k=0;k<N;k++) mg[k]=hypot(ot[2*k],ot[2*k+1]);
    int c=0;
    for(size_t j=0;j<nb;j++){
      size_t lo=ws+j*binsize, hi=lo+binsize; if(hi>we) hi=we;
      /* brute force: the loudest bin member, and whether it clears the floor */
      size_t best=lo; for(size_t k=lo;k<hi;k++) if(mg[k]>mg[best]) best=k;
      ap_peak *q=&pk[(size_t)b*nb+j];
      if(mg[best]<=(double)T){
        CK(q->index==-1,"N=%zu b=%d bin %zu: expected empty, got index %ld (mag %g, floor %g)",
           N,b,j,q->index,(double)q->magnitude,(double)T);
        CK(q->magnitude==0.f,"N=%zu b=%d bin %zu: empty bin must report magnitude 0",N,b,j);
        continue;
      }
      c++;
      CK((size_t)q->index==best,"N=%zu b=%d bin %zu: index %ld, brute force says %zu",
         N,b,j,q->index,best);
      CK(q->index>=(long)lo && q->index<(long)hi,
         "N=%zu b=%d bin %zu: index %ld outside [%zu,%zu)",N,b,j,q->index,lo,hi);
      CK(fabs(q->magnitude-mg[best])<=1e-5*mg[best]+1e-4,
         "N=%zu b=%d bin %zu: magnitude %g vs %g",N,b,j,(double)q->magnitude,mg[best]);
      double dr=q->re-ot[2*best], di=q->im-ot[2*best+1];
      CK(hypot(dr,di)<=1e-5*mg[best]+1e-4,
         "N=%zu b=%d bin %zu: complex value off by %g",N,b,j,hypot(dr,di));
    }
    CK(cnt[b]==c,"N=%zu b=%d: count %d, expected %d",N,b,cnt[b],c);
    sum+=c;
  }
  CK(tot==sum,"N=%zu: total %d != sum %d",N,tot,sum);
  free(in);free(ot);free(mg);free(srt);free(pk);free(cnt); ap_destroy(p);
}

int main(void){
  if(!ap_supported(1024)){ printf("test_binmax: unsupported CPU, skipped\n"); return 0; }
  const int quick = getenv("AP_QUICK") != NULL;
  size_t Ns[]={1024,4096,16384,65536};
  int nN = quick?2:4;
  for(int i=0;i<nN;i++){
    size_t N=Ns[i]; int B=quick?4:8;
    for(size_t bs=16; bs<=N; bs*=4){
      run(N,B,bs,AP_FORWARD,0,N,0);
      run(N,B,bs,AP_FORWARD,0,N,1);
      run(N,B,bs,AP_BACKWARD,0,N,1);
    }
    /* windowed, and deliberately not a multiple of the bin size */
    run(N,B,N/8,AP_FORWARD,N/5,(size_t)(N*0.7),1);
    run(N,B,N/8+3,AP_FORWARD,N/5+1,(size_t)(N*0.7),1);
    run(N,B,97,AP_FORWARD,N/4,N/2,1);          /* ragged bins, straddles blocks */
    run(N,B,N,AP_FORWARD,0,N,1);               /* one bin: global max */
  }
  printf("test_binmax %29s %d checks, %d failures  [%s]\n","",checks,fails,fails?"FAIL":"ok");
  return fails?1:0;
}
