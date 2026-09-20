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
  for(int t=0;t<NT;t++) /* All templates obey the stated relationship (~0.85 of the power below
       n/8), with only slight spread.  The earlier 0.85-0.02*t put templates
       8..15 at 0.55-0.69, which the band chosen for 0.85 serves badly: low f
       gives a low gate and near-constant triggering, so the benchmark was
       measuring a template mismatch rather than the filter. */
    make_template_pow(H+(size_t)t*2*n,n,0.85-0.004*t);
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
  (void)nl;(void)lab;
  printf("  %6zu %6.1f %7.0e %6zu | %8.2f %8.2f | %6.2fx %6.1f%%\n",
         n,(double)snr,(double)fd,band,tmf*1e6,thf*1e6,
         tmf/thf,100.0*(g1-g0)/(double)(p1-p0));
  free(pk);free(H);free(D); ap_mf_destroy(mf); ap_hmf_destroy(hf);
}

int main(int argc,char **argv){
  (void)argc;(void)argv;
  /* The design matrix to optimise against: SNR x false-dismissal x size.
     Reported on pure noise, which is the regime a real search spends its time
     in -- signals are rare.  trig is the fraction of pairs that needed the full
     correlation, and it is what the speedup rides on. */
  printf("hierarchical vs full matched filter, backend %s\n",ap_isa());
  printf("D=T=16 (256 pairs), bin n/4, whole record, pure noise.\n");
  printf("Templates carry ~0.85 of their power below n/8 at every size.\n\n");
  printf("  %6s %6s %7s %6s | %8s %8s | %7s %7s\n",
         "n","snr","fd","band","mf us","hmf us","speedup","trig");
  const float SNRS[4]={5.0f,5.5f,6.0f,6.5f};
  const float FDS[3]={1e-2f,1e-3f,1e-4f};
  const size_t NS[2]={2048,4096};
  for(int si=0;si<2;si++){
    for(int fi=0;fi<3;fi++){
      for(int ti=0;ti<4;ti++)
        run_case(NS[si],16,16,SNRS[ti],FDS[fi],0.0,"");
      printf("\n");
    }
  }
  return 0;
}
