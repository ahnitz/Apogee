/* Paired A/B of two builds of the library, interleaved in one process.
 *
 * The reason this exists: run-to-run spread on this machine is ~12% at 2^18,
 * which is larger than most changes worth making.  Comparing two sequential
 * runs cannot see a 5% effect.  Here the two builds alternate inside one timed
 * sweep, so drift hits both equally, and the statistic reported is the
 * distribution of per-round ratios plus a sign test - not a difference of minima.
 *
 *   make libapogee.so                       # build the current tree
 *   cp libapogee.so /tmp/base.so            # keep it as the baseline
 *   ...edit, rebuild...
 *   ./bench/ab /tmp/base.so libapogee.so
 *
 * It also checks the two builds agree on every peak before timing anything, so a
 * change that is fast because it is wrong gets caught here rather than later.
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include <dlfcn.h>
#include "apogee.h"

static double now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+1e-9*t.tv_nsec;}
static unsigned long long rs=88172645463325252ULL;
static double u(void){rs^=rs<<13;rs^=rs>>7;rs^=rs<<17;return (double)(rs>>11)/9007199254740992.0;}
static double gs(void){return sqrt(-2.0*log(u()+1e-300))*cos(2*M_PI*u());}
static int cmpd(const void*a,const void*b){double x=*(const double*)a,y=*(const double*)b;return x<y?-1:x>y;}
static int cmpdd(const void*a,const void*b){double x=*(const double*)a,y=*(const double*)b;return x<y?1:(x>y?-1:0);}

/* Two-sided sign test.  Every wrong call on this project came from reading a
   difference smaller than the machine's own drift, so the harness decides
   significance itself rather than leaving it to whoever is squinting at the
   column.  Exact binomial, no approximation - R is small. */
static double sign_p(int wins,int R){
  if(R<1) return 1.0;
  int k = wins < R-wins ? wins : R-wins;
  double tail=0, c=1;                       /* c = C(R,i) built up iteratively */
  for(int i=0;i<=k;i++){
    tail += c;
    c = c*(R-i)/(i+1);
  }
  double p = 2.0*tail*pow(0.5,(double)R);
  return p>1.0?1.0:p;
}

/* Plans are allocated once per size, and whichever library creates its plan first
   gets a different set of addresses.  At 2^12 the buffers are ~36 KiB, so which L1
   sets they land on is decided by those addresses - and two byte-identical builds
   measured 2/24 wins, p=3.6e-5, purely from that.  So each size is run over
   several trials with the creation order swapped, and the per-round ratios are
   pooled: layout luck averages out instead of masquerading as a result. */
#define TRIALS 4
/* Resolution floor.  The two libraries are separately mapped, so their code and
   their plan buffers sit at different addresses and alias caches differently;
   between two byte-identical builds that is worth a couple of percent and is
   statistically significant if you only ask the sign test.  So a verdict needs
   both significance AND an effect bigger than this.  Calibrated by demanding
   that an identical pair reads "noise". */
#define MIN_EFFECT 0.03

typedef struct {
  void *h; const char *path;
  ap_plan *(*create)(size_t);
  void (*destroy)(ap_plan*);
  void (*fft)(ap_plan*,const float*,float*,int);
  int (*many)(ap_plan*,const float*,size_t,int,int,float,ap_peak*,int*,int,size_t,size_t);
  const char *(*isa)(void);
} lib;

static int open_lib(lib *L,const char *path){
  L->h=dlopen(path,RTLD_NOW|RTLD_LOCAL|RTLD_DEEPBIND);
  if(!L->h){ fprintf(stderr,"dlopen %s: %s\n",path,dlerror()); return -1; }
  L->path=path;
  L->create=dlsym(L->h,"ap_create"); L->destroy=dlsym(L->h,"ap_destroy");
  L->fft=dlsym(L->h,"ap_fft"); L->many=dlsym(L->h,"ap_topk_many");
  L->isa=dlsym(L->h,"ap_isa");
  if(!L->create||!L->many){ fprintf(stderr,"%s: missing symbols\n",path); return -1; }
  return 0;
}

int main(int argc,char**argv){
  if(argc<3){ fprintf(stderr,
      "usage: %s <libA.so> <libB.so> [-b batch] [-k K] [-r rounds] [-t] [lg ...]\n"
      "  -t              use a detection floor (~1 crossing per 1000 bins)\n"
      "  -e NAME=a,b     set NAME to a around A's plan create and to b around B's,\n"
      "                  so runtime-switched knobs can be compared without two builds\n",
      argv[0]); return 2; }
  lib A,B;
  if(open_lib(&A,argv[1])||open_lib(&B,argv[2])) return 1;

  int Bsz=16,K=8,rounds=0,useThr=0;
  int lgs[32],nlg=0;
  /* Several knobs here are read by getenv() at plan-creation time, so the two
     sides can differ on one without needing two builds: set the variable one way
     around A's create and the other way around B's.  -e NAME=valA,valB */
  const char *envar=NULL,*eva=NULL,*evb=NULL;
  char ebuf[256];
  for(int i=3;i<argc;i++){
    if(!strcmp(argv[i],"-b")) Bsz=atoi(argv[++i]);
    else if(!strcmp(argv[i],"-k")) K=atoi(argv[++i]);
    else if(!strcmp(argv[i],"-r")) rounds=atoi(argv[++i]);
    else if(!strcmp(argv[i],"-t")) useThr=1;
    else if(!strcmp(argv[i],"-e")){
      snprintf(ebuf,sizeof ebuf,"%s",argv[++i]);
      char *eq=strchr(ebuf,'='), *cm=eq?strchr(eq,','):NULL;
      if(!eq||!cm){ fprintf(stderr,"-e wants NAME=valA,valB\n"); return 2; }
      *eq=0; *cm=0; envar=ebuf; eva=eq+1; evb=cm+1;
    }
    else if(nlg<32) lgs[nlg++]=atoi(argv[i]);
  }
  if(!nlg){ int d[]={10,12,14,16,18,20}; for(unsigned i=0;i<6;i++) lgs[nlg++]=d[i]; }

  printf("A = %s   B = %s   (batch %d, K %d%s)\n",argv[1],argv[2],Bsz,K,useThr?", floor on":"");
  if(envar) printf("    %s: A=%s  B=%s\n",envar,eva,evb);
  printf("%-6s %10s %10s %8s %8s %7s %-10s %s\n",
         "N","A median","B median","B/A","spread","B wins","verdict","check");

  for(int i=0;i<nlg;i++){
    size_t N=(size_t)1<<lgs[i];
    size_t bytes=(size_t)N*Bsz*8;
    float *in=aligned_alloc(64,bytes), *ref=aligned_alloc(64,N*8);
    if(!in||!ref){ printf("2^%-4d  (out of memory)\n",lgs[i]); continue; }
    rs=(unsigned long long)lgs[i]*2654435761u+1;
    for(size_t j=0;j<(size_t)N*Bsz;j++){ in[2*j]=(float)gs(); in[2*j+1]=(float)gs(); }

    int R = rounds ? rounds : (N<=(1u<<14)?12:(N<=(1u<<17)?8:4));
    if(R&1) R++;
    int TOT=R*TRIALS;
    double *ra=malloc(TOT*sizeof(double)),*rb=malloc(TOT*sizeof(double)),*rt=malloc(TOT*sizeof(double));
    double *sa=malloc(TOT*sizeof(double)),*sb=malloc(TOT*sizeof(double));
    int bwin=0,bad=0,n=0;
    float thr=0.f;

    for(int tr=0;tr<TRIALS;tr++){
      ap_plan *pa,*pb;
      if(tr&1){   /* swap which library allocates first */
        if(envar) setenv(envar,evb,1);
        pb=B.create(N);
        if(envar) setenv(envar,eva,1);
        pa=A.create(N);
      } else {
        if(envar) setenv(envar,eva,1);
        pa=A.create(N);
        if(envar) setenv(envar,evb,1);
        pb=B.create(N);
      }
      if(envar) unsetenv(envar);
      if(!pa||!pb){ printf("2^%-4d  (unsupported)\n",lgs[i]); goto next_size; }

      if(tr==0 && useThr){
        A.fft(pa,in,ref,AP_FORWARD);
        double *m=malloc(N*sizeof(double));
        for(size_t k=0;k<N;k++) m[k]=hypot(ref[2*k],ref[2*k+1]);
        qsort(m,N,sizeof(double),cmpdd);
        size_t q=N/1000; if(q<1) q=1;
        thr=(float)(0.5*(m[q]+m[q+1])); free(m);
      }

      ap_peak *ka=malloc((size_t)Bsz*K*sizeof(ap_peak)),*kb=malloc((size_t)Bsz*K*sizeof(ap_peak));
      int *ca=malloc(Bsz*4),*cb=malloc(Bsz*4);
      A.many(pa,in,N,Bsz,K,thr,ka,ca,AP_FORWARD,0,N);
      B.many(pb,in,N,Bsz,K,thr,kb,cb,AP_FORWARD,0,N);
      for(int b=0;b<Bsz && !bad;b++){
        if(ca[b]!=cb[b]){ bad=1; break; }
        for(int a=0;a<ca[b];a++){
          ap_peak *x=&ka[b*K+a],*y=&kb[b*K+a];
          if(x->index!=y->index || hypot(x->re-y->re,x->im-y->im) > 1e-4*x->magnitude){ bad=1; break; }
        }
      }
      /* A fresh plan's buffers are newly mapped, so the first passes take page
         faults - at 2^12 that showed up as a single round 47x the median and a
         spread of several thousand percent.  Warm until the pages are resident. */
      for(int w=0;w<6;w++){ A.many(pa,in,N,Bsz,K,thr,ka,ca,AP_FORWARD,0,N);
                            B.many(pb,in,N,Bsz,K,thr,kb,cb,AP_FORWARD,0,N); }
      for(int r=0;r<R;r++){
        double t0,t1,t2,ta,tb;
        if(r&1){
          t0=now(); A.many(pa,in,N,Bsz,K,thr,ka,ca,AP_FORWARD,0,N);
          t1=now(); B.many(pb,in,N,Bsz,K,thr,kb,cb,AP_FORWARD,0,N); t2=now();
          ta=(t1-t0)/Bsz; tb=(t2-t1)/Bsz;
        } else {
          t0=now(); B.many(pb,in,N,Bsz,K,thr,kb,cb,AP_FORWARD,0,N);
          t1=now(); A.many(pa,in,N,Bsz,K,thr,ka,ca,AP_FORWARD,0,N); t2=now();
          tb=(t1-t0)/Bsz; ta=(t2-t1)/Bsz;
        }
        ra[n]=ta; rb[n]=tb; rt[n]=tb/ta; if(tb<ta) bwin++; n++;
      }
      free(ka);free(kb);free(ca);free(cb);
      A.destroy(pa); B.destroy(pb);
    }

    memcpy(sa,ra,n*sizeof(double)); memcpy(sb,rb,n*sizeof(double));
    qsort(sa,n,sizeof(double),cmpd); qsort(sb,n,sizeof(double),cmpd);
    qsort(rt,n,sizeof(double),cmpd);
    { double ma=sa[n/2],mb=sb[n/2];
      double spread=(sa[n-1]-sa[0])/ma;
      double p=sign_p(bwin,n);
      const char *verdict;
      double eff=rt[n/2]-1.0;
      if(p>0.01)                      verdict="noise";
      else if(fabs(eff)<MIN_EFFECT)   verdict="< 3%";
      else if(eff<0)                  verdict="B FASTER";
      else                            verdict="B slower";
      printf("2^%-4d %10.3f %10.3f %8.3f %7.0f%% %5d/%-3d %-10s %s\n",
             lgs[i],ma*1e6,mb*1e6,rt[n/2],spread*100,bwin,n,verdict,
             bad?"MISMATCH":"same peaks");
    }
next_size:
    free(sa);free(sb);
    free(ra);free(rb);free(rt);
    free(in); free(ref);
  }
  printf("\nB/A below 1.0 means B is faster.  'verdict' is a two-sided sign test at\n"
         "p<0.01 over the per-round pairings, pooled across %d plan-layout trials,\n"
         "AND an effect over %.0f%%.  Below that, two identical builds differ by as much\n"
         "just from where their code and buffers happen to be mapped.\n",
         TRIALS,MIN_EFFECT*100);
  return 0;
}
