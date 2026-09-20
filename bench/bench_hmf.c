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

static void make_template(float *H,size_t n,double s){
  double e=0;
  memset(H,0,2*n*sizeof(float));
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
  for(int t=0;t<NT;t++) make_template(H+(size_t)t*2*n,n,-0.9-0.05*t);
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
  printf("  %-22s band=%-6zu U=%d K=%-2d  mf=%7.2f us  hmf=%7.2f us  %5.2fx  trig=%5.1f%%\n",
         lab,band,u,k,tmf*1e6,thf*1e6,tmf/thf,100.0*(g1-g0)/(double)(p1-p0));
  free(pk);free(H);free(D); ap_mf_destroy(mf); ap_hmf_destroy(hf);
}

int main(int argc,char **argv){
  (void)argc;(void)argv;
  printf("hierarchical vs full matched filter (backend %s), per pair\n\n",ap_isa());
  printf(" pure noise - the gate should almost never open\n");
  run_case(2048,16,16,5.5f,1e-2f,0.0,"2^11 snr5.5 fd1e-2");
  run_case(4096,16,16,5.5f,1e-2f,0.0,"2^12 snr5.5 fd1e-2");
  run_case(4096,16,16,5.0f,1e-4f,0.0,"2^12 snr5.0 fd1e-4");
  run_case(8192,16,16,6.0f,1e-2f,0.0,"2^13 snr6.0 fd1e-2");
  run_case(16384,8,8, 5.5f,1e-2f,0.0,"2^14 snr5.5 fd1e-2");
  printf("\n every data segment carries a signal - the worst case for the gate\n");
  run_case(2048,16,16,5.5f,1e-2f,7.0,"2^11 snr5.5 fd1e-2");
  run_case(4096,16,16,5.5f,1e-2f,7.0,"2^12 snr5.5 fd1e-2");
  run_case(4096,16,16,5.0f,1e-4f,7.0,"2^12 snr5.0 fd1e-4");
  run_case(8192,16,16,6.0f,1e-2f,7.0,"2^13 snr6.0 fd1e-2");
  run_case(16384,8,8, 5.5f,1e-2f,7.0,"2^14 snr5.5 fd1e-2");
  return 0;
}
