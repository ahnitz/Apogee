/* Paired A/B of two builds of the library, interleaved in one process.
 *
 * The reason this exists: run-to-run spread on this machine is ~12% at 2^18,
 * which is larger than most changes worth making.  Comparing two sequential
 * runs cannot see a 5% effect.  Here the two builds alternate inside one timed
 * sweep, so drift hits both equally, and the statistic reported is the
 * distribution of per-round ratios plus a sign test - not a difference of minima.
 *
 *   make libpeakfft.so                       # build the current tree
 *   cp libpeakfft.so /tmp/base.so            # keep it as the baseline
 *   ...edit, rebuild...
 *   ./bench/ab /tmp/base.so libpeakfft.so
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
#include "peakfft.h"

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

typedef struct {
  void *h; const char *path;
  pf_plan *(*create)(size_t);
  void (*destroy)(pf_plan*);
  void (*fft)(pf_plan*,const float*,float*,int);
  int (*many)(pf_plan*,const float*,size_t,int,int,float,pf_peak*,int*,int,size_t,size_t);
  const char *(*isa)(void);
} lib;

static int open_lib(lib *L,const char *path){
  L->h=dlopen(path,RTLD_NOW|RTLD_LOCAL|RTLD_DEEPBIND);
  if(!L->h){ fprintf(stderr,"dlopen %s: %s\n",path,dlerror()); return -1; }
  L->path=path;
  L->create=dlsym(L->h,"pf_create"); L->destroy=dlsym(L->h,"pf_destroy");
  L->fft=dlsym(L->h,"pf_fft"); L->many=dlsym(L->h,"pf_topk_many");
  L->isa=dlsym(L->h,"pf_isa");
  if(!L->create||!L->many){ fprintf(stderr,"%s: missing symbols\n",path); return -1; }
  return 0;
}

int main(int argc,char**argv){
  if(argc<3){ fprintf(stderr,
      "usage: %s <libA.so> <libB.so> [-b batch] [-k K] [-r rounds] [-t] [lg ...]\n"
      "  -t  use a detection floor (~1 crossing per 1000 bins)\n",argv[0]); return 2; }
  lib A,B;
  if(open_lib(&A,argv[1])||open_lib(&B,argv[2])) return 1;

  int Bsz=16,K=8,rounds=0,useThr=0;
  int lgs[32],nlg=0;
  for(int i=3;i<argc;i++){
    if(!strcmp(argv[i],"-b")) Bsz=atoi(argv[++i]);
    else if(!strcmp(argv[i],"-k")) K=atoi(argv[++i]);
    else if(!strcmp(argv[i],"-r")) rounds=atoi(argv[++i]);
    else if(!strcmp(argv[i],"-t")) useThr=1;
    else if(nlg<32) lgs[nlg++]=atoi(argv[i]);
  }
  if(!nlg){ int d[]={10,12,14,16,18,20}; for(unsigned i=0;i<6;i++) lgs[nlg++]=d[i]; }

  printf("A = %s   B = %s   (batch %d, K %d%s)\n",argv[1],argv[2],Bsz,K,useThr?", floor on":"");
  printf("%-6s %10s %10s %8s %8s %7s %-10s %s\n",
         "N","A median","B median","B/A","spread","B wins","verdict","check");

  for(int i=0;i<nlg;i++){
    size_t N=(size_t)1<<lgs[i];
    size_t bytes=(size_t)N*Bsz*8;
    float *in=aligned_alloc(64,bytes), *ref=aligned_alloc(64,N*8);
    if(!in||!ref){ printf("2^%-4d  (out of memory)\n",lgs[i]); continue; }
    rs=(unsigned long long)lgs[i]*2654435761u+1;
    for(size_t j=0;j<(size_t)N*Bsz;j++){ in[2*j]=(float)gs(); in[2*j+1]=(float)gs(); }

    pf_plan *pa=A.create(N), *pb=B.create(N);
    if(!pa||!pb){ printf("2^%-4d  (unsupported)\n",lgs[i]); free(in); free(ref); continue; }

    float thr=0.f;
    if(useThr){
      A.fft(pa,in,ref,PF_FORWARD);
      double *m=malloc(N*sizeof(double));
      for(size_t k=0;k<N;k++) m[k]=hypot(ref[2*k],ref[2*k+1]);
      qsort(m,N,sizeof(double),cmpdd);
      size_t q=N/1000; if(q<1) q=1;
      thr=(float)(0.5*(m[q]+m[q+1])); free(m);
    }

    pf_peak *ka=malloc((size_t)Bsz*K*sizeof(pf_peak)),*kb=malloc((size_t)Bsz*K*sizeof(pf_peak));
    int *ca=malloc(Bsz*4),*cb=malloc(Bsz*4);
    A.many(pa,in,N,Bsz,K,thr,ka,ca,PF_FORWARD,0,N);
    B.many(pb,in,N,Bsz,K,thr,kb,cb,PF_FORWARD,0,N);
    int bad=0;
    for(int b=0;b<Bsz;b++){
      if(ca[b]!=cb[b]){ bad=1; break; }
      for(int a=0;a<ca[b];a++){
        pf_peak *x=&ka[b*K+a],*y=&kb[b*K+a];
        if(x->index!=y->index){ bad=1; break; }
        double d=hypot(x->re-y->re,x->im-y->im);
        if(d > 1e-4*x->magnitude){ bad=1; break; }
      }
      if(bad) break;
    }

    /* R must be even: the order alternates every round, so an odd R gives one
       side the disadvantageous first-slot once more than the other and shows up
       as a consistent few-percent bias even between identical builds. */
    int R = rounds ? rounds : (N<=(1u<<14)?24:(N<=(1u<<17)?16:8));
    if(R&1) R++;
    double *ra=malloc(R*sizeof(double)),*rb=malloc(R*sizeof(double)),*rt=malloc(R*sizeof(double));
    for(int w=0;w<2;w++){ A.many(pa,in,N,Bsz,K,thr,ka,ca,PF_FORWARD,0,N);
                          B.many(pb,in,N,Bsz,K,thr,kb,cb,PF_FORWARD,0,N); }
    int bwin=0;
    for(int r=0;r<R;r++){
      /* alternate the order each round so neither side always runs on a warm cache */
      double t0,t1,t2;
      if(r&1){
        t0=now(); A.many(pa,in,N,Bsz,K,thr,ka,ca,PF_FORWARD,0,N);
        t1=now(); B.many(pb,in,N,Bsz,K,thr,kb,cb,PF_FORWARD,0,N); t2=now();
        ra[r]=(t1-t0)/Bsz; rb[r]=(t2-t1)/Bsz;
      } else {
        t0=now(); B.many(pb,in,N,Bsz,K,thr,kb,cb,PF_FORWARD,0,N);
        t1=now(); A.many(pa,in,N,Bsz,K,thr,ka,ca,PF_FORWARD,0,N); t2=now();
        rb[r]=(t1-t0)/Bsz; ra[r]=(t2-t1)/Bsz;
      }
      rt[r]=rb[r]/ra[r];
      if(rb[r]<ra[r]) bwin++;
    }
    qsort(ra,R,sizeof(double),cmpd); qsort(rb,R,sizeof(double),cmpd);
    qsort(rt,R,sizeof(double),cmpd);
    double ma=ra[R/2],mb=rb[R/2];
    double spread=(ra[R-1]-ra[0])/ma;          /* how noisy the machine is right now */
    double p=sign_p(bwin,R);
    const char *verdict;
    /* p<0.01 rather than 0.05: a sweep is six rows, so a 5% threshold yields a
       false call roughly every three runs, which is exactly often enough to
       believe one. */
    if(p>0.01)              verdict="noise";
    else if(rt[R/2]<0.98)   verdict="B FASTER";
    else if(rt[R/2]>1.02)   verdict="B slower";
    else                    verdict="same";
    printf("2^%-4d %10.3f %10.3f %8.3f %7.0f%% %5d/%-2d %-10s %s\n",
           lgs[i],ma*1e6,mb*1e6,rt[R/2],spread*100,bwin,R,verdict,
           bad?"MISMATCH":"same peaks");
    free(ra);free(rb);free(rt);free(ka);free(kb);free(ca);free(cb);
    A.destroy(pa); B.destroy(pb); free(in); free(ref);
  }
  printf("\nB/A below 1.0 means B is faster.  'verdict' is a two-sided sign test at\n"
         "p<0.05 over the per-round pairings; 'noise' means the machine could not\n"
         "separate them and the ratio should not be reported as a result.\n");
  return 0;
}
