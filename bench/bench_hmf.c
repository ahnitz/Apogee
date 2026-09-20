/* Hierarchical filter against the ordinary one, on the same data.
 *
 * Both filters get identical inputs and produce identical peaks (test_hmf
 * enforces that), so the only thing being measured is what the gate saves.
 *
 * The data matters here in a way it does not for the plain filter: the
 * hierarchical path's cost depends on how often the gate opens, so a benchmark
 * on pure noise and one on signal-rich data measure different things.  Both are
 * reported.  A single "speedup" number without the trigger rate beside it is
 * not interpretable.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include "apogee.h"

static unsigned long rs=2463534242UL;
static double urand(void){ rs^=rs<<13; rs^=rs>>7; rs^=rs<<17; return (rs>>11)*(1.0/9007199254740992.0); }
static double nrand(void){ double u=urand(),v=urand(); if(u<1e-300)u=1e-300;
                           return sqrt(-2*log(u))*cos(2*M_PI*v); }
static double now(void){ struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
                         return t.tv_sec+1e-9*t.tv_nsec; }


/* Build a template with a stated fraction of its SNR below n/8.
 *
 * The band edge is fixed in Hz, not in bins: at a 2048 Hz sample rate, 256 Hz
 * lands at bin 256*n/2048 = n/8 for any n.  So the reference band is n/8 at
 * every size, and growing n analyses more time rather than more bandwidth.
 *
 * `want` is a POWER fraction (0.85 power is 0.92 SNR -- the two are easy to
 * conflate and differ substantially).  Using
 * a fixed power-law exponent instead makes the template far more concentrated
 * as n grows -- f^-0.9 puts 99% of its power below n/8 at 2^20 -- which flatters
 * every hierarchical measurement into meaninglessness.
 */
static void make_template_pow(float *H,size_t n,double want){
  const size_t mref=n/8;
  double lo=-8.0,hi=4.0;
  for(int it=0;it<200;it++){
    double s=0.5*(lo+hi), tot=0, low=0;
    for(size_t f=1;f<n/2;f++){ double p=pow((double)f,2*s); tot+=p; if(f<mref) low+=p; }
    if(low/tot<want) hi=s; else lo=s;
  }
  const double s=0.5*(lo+hi);
  double e=0;
  for(size_t k=0;k<2*n;k++) H[k]=0.f;
  for(size_t f=1;f<n/2;f++){ double a=pow((double)f,s); H[2*f]=(float)a; e+=a*a; }
  e=sqrt(e);
  for(size_t f=1;f<n/2;f++) H[2*f]/=(float)e;
}

static void make_data(float *D,const float *H,size_t n,double amp,size_t lag){
  for(size_t f=0;f<n;f++){
    double re=nrand(), im=nrand();
    double c=cos(-2*M_PI*(double)f*lag/(double)n), s=sin(-2*M_PI*(double)f*lag/(double)n);
    D[2*f]  =(float)(re+amp*(H[2*f]*c-H[2*f+1]*s));
    D[2*f+1]=(float)(im+amp*(H[2*f]*s+H[2*f+1]*c));
  }
}

static void run_case(size_t n,int ND,int NT,float snr,float fd,double amp,const char *lab){
  float *H=malloc(2*n*sizeof(float)*NT), *D=malloc(2*n*sizeof(float)*ND);
  for(int t=0;t<NT;t++) make_template_pow(H+(size_t)t*2*n,n,0.85-0.02*t);
  for(int d=0;d<ND;d++) make_data(D+(size_t)d*2*n,H,n,amp,(size_t)(400+31*d));

  ap_mf_plan  *mf =ap_mf_create(n,ND,NT);
  ap_hmf_plan *hf =ap_hmf_create(n,ND,NT,snr,fd);
  if(!mf||!hf){ printf("  %-22s SKIP\n",lab); return; }
  for(int d=0;d<ND;d++){ ap_mf_set_data(mf,d,D+(size_t)d*2*n); ap_hmf_set_data(hf,d,D+(size_t)d*2*n); }
  for(int t=0;t<NT;t++){ ap_mf_set_template(mf,t,H+(size_t)t*2*n); ap_hmf_set_template(hf,t,H+(size_t)t*2*n); }

  const size_t bs=n/4, start=0, end=n;
  size_t nb=ap_mf_nbins(mf,bs,start,end);
  ap_peak *pk=calloc((size_t)ND*NT*nb,sizeof(ap_peak));
  const float thr=(float)snr;

  int reps = n<=8192 ? 20 : 5;
  for(int i=0;i<3;i++) ap_mf_run(mf,0,ND,0,NT,bs,thr,pk,NULL,start,end);
  double t0=now();
  for(int i=0;i<reps;i++) ap_mf_run(mf,0,ND,0,NT,bs,thr,pk,NULL,start,end);
  double tmf=(now()-t0)/reps/((double)ND*NT);

  for(int i=0;i<3;i++) ap_hmf_run(hf,0,ND,0,NT,bs,thr,pk,NULL,start,end);
  long p0,g0; ap_hmf_stats(hf,&p0,&g0);
  t0=now();
  for(int i=0;i<reps;i++) ap_hmf_run(hf,0,ND,0,NT,bs,thr,pk,NULL,start,end);
  double thf=(now()-t0)/reps/((double)ND*NT);
  long p1,g1; ap_hmf_stats(hf,&p1,&g1);

  size_t band; int u,k; ap_hmf_config(hf,&band,&u,&k);
  /* Normalise by n*log2(n): the full inverse's own work.  ps/(n log n) makes
     sizes comparable and shows whether a route is hitting its flop bound or
     paying overhead. */
  double nl = (double)n * log2((double)n);
  printf("  %-20s %7zu %6zu | %8.2f %8.2f | %7.1f %7.1f | %6.2fx %6.1f%%\n",
         lab,n,band,tmf*1e6,thf*1e6,tmf*1e12/nl,thf*1e12/nl,
         tmf/thf,100.0*(g1-g0)/(double)(p1-p0));
  free(pk);free(H);free(D); ap_mf_destroy(mf); ap_hmf_destroy(hf);
}

int main(int argc,char **argv){
  (void)argc;(void)argv;
  printf("hierarchical vs full matched filter, backend %s\n",ap_isa());
  printf("D=T=16 (16x16=256 pairs), bin n/4, whole record searched.\n");
  printf("us/pair is wall time per (data,template) pair; ps/nlogn normalises by\n");
  printf("the full inverse's own work so sizes are comparable.\n\n");
  printf("  %-20s %7s %6s | %8s %8s | %7s %7s | %6s %7s\n",
         "case","n","band","mf us","hmf us","mf ps","hmf ps","speedup","trig");
  printf(" pure noise - the gate should almost never open\n");
  run_case(2048,16,16,5.5f,1e-2f,0.0,"snr5.5 fd1e-2");
  run_case(4096,16,16,5.5f,1e-2f,0.0,"snr5.5 fd1e-2");
  run_case(4096,16,16,5.0f,1e-4f,0.0,"snr5.0 fd1e-4");
  run_case(8192,16,16,6.0f,1e-2f,0.0,"snr6.0 fd1e-2");
  run_case(16384,16,16,5.5f,1e-2f,0.0,"snr5.5 fd1e-2");
  run_case(65536, 8, 8, 5.5f,1e-2f,0.0,"snr5.5 fd1e-2");
  run_case(262144,4, 4, 5.5f,1e-2f,0.0,"snr5.5 fd1e-2");
  run_case(1048576,2,2, 5.5f,1e-2f,0.0,"snr5.5 fd1e-2");
  printf("\n every data segment carries a signal - the worst case for the gate\n");
  run_case(2048,16,16,5.5f,1e-2f,7.0,"snr5.5 fd1e-2");
  run_case(4096,16,16,5.5f,1e-2f,7.0,"snr5.5 fd1e-2");
  run_case(4096,16,16,5.0f,1e-4f,7.0,"snr5.0 fd1e-4");
  run_case(8192,16,16,6.0f,1e-2f,7.0,"snr6.0 fd1e-2");
  run_case(16384,16,16,5.5f,1e-2f,7.0,"snr5.5 fd1e-2");
  return 0;
}
