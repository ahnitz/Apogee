#ifndef PF_TESTUTIL_H
#define PF_TESTUTIL_H
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
/* Test helpers are shared across binaries; not every one uses all of them. */
#if defined(__GNUC__)
#pragma GCC diagnostic ignored "-Wunused-function"
#endif
static int pf_fail_count = 0, pf_check_count = 0;
#define CHECK(cond, ...) do{ pf_check_count++; if(!(cond)){ pf_fail_count++; \
  printf("  FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } }while(0)
#define CHECK_LE(v, lim, ...) do{ pf_check_count++; double _v=(v); if(!(_v<=(lim))){ pf_fail_count++; \
  printf("  FAIL %s:%d: %s = %.4e > %.4e  ", __FILE__, __LINE__, #v, _v, (double)(lim)); \
  printf(__VA_ARGS__); printf("\n"); } }while(0)
static int pf_report(const char *name){
  printf("%-34s %3d checks, %d failures  %s\n", name, pf_check_count, pf_fail_count,
         pf_fail_count?"[FAIL]":"[ok]");
  return pf_fail_count!=0;
}
static unsigned long long pf_rs = 88172645463325252ULL;
static void pf_seed(unsigned long long s){ pf_rs = s?s:1; }
static double pf_u(void){ pf_rs^=pf_rs<<13; pf_rs^=pf_rs>>7; pf_rs^=pf_rs<<17;
                          return (double)(pf_rs>>11)/9007199254740992.0; }
static double pf_gauss(void){ return sqrt(-2.0*log(pf_u()+1e-300))*cos(2.0*M_PI*pf_u()); }
/* O(N^2) reference DFT in double precision */
static void pf_ref_dft(const float *in, double *out, int N){
  for(int k=0;k<N;k++){ double sr=0, si=0;
    for(int n=0;n<N;n++){ double a=-2.0*M_PI*(double)n*k/N, c=cos(a), s=sin(a);
      sr += in[2*n]*c - in[2*n+1]*s; si += in[2*n]*s + in[2*n+1]*c; }
    out[2*k]=sr; out[2*k+1]=si; }
}
static void *pf_alloc(size_t bytes){ void *p=NULL;
  if(posix_memalign(&p,4096,bytes)) { perror("alloc"); exit(1);} return p; }
#endif
