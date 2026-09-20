#ifndef AP_TESTUTIL_H
#define AP_TESTUTIL_H
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
/* Test helpers are shared across binaries; not every one uses all of them. */
#if defined(__GNUC__)
#pragma GCC diagnostic ignored "-Wunused-function"
#endif
static int ap_fail_count = 0, ap_check_count = 0;
#define CHECK(cond, ...) do{ ap_check_count++; if(!(cond)){ ap_fail_count++; \
  printf("  FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } }while(0)
#define CHECK_LE(v, lim, ...) do{ ap_check_count++; double _v=(v); if(!(_v<=(lim))){ ap_fail_count++; \
  printf("  FAIL %s:%d: %s = %.4e > %.4e  ", __FILE__, __LINE__, #v, _v, (double)(lim)); \
  printf(__VA_ARGS__); printf("\n"); } }while(0)
static int ap_report(const char *name){
  printf("%-34s %3d checks, %d failures  %s\n", name, ap_check_count, ap_fail_count,
         ap_fail_count?"[FAIL]":"[ok]");
  return ap_fail_count!=0;
}
static unsigned long long ap_rs = 88172645463325252ULL;
static void ap_seed(unsigned long long s){ ap_rs = s?s:1; }
static double ap_u(void){ ap_rs^=ap_rs<<13; ap_rs^=ap_rs>>7; ap_rs^=ap_rs<<17;
                          return (double)(ap_rs>>11)/9007199254740992.0; }
static double ap_gauss(void){ return sqrt(-2.0*log(ap_u()+1e-300))*cos(2.0*M_PI*ap_u()); }
/* O(N^2) reference DFT in double precision */
static void ap_ref_dft(const float *in, double *out, int N){
  for(int k=0;k<N;k++){ double sr=0, si=0;
    for(int n=0;n<N;n++){ double a=-2.0*M_PI*(double)n*k/N, c=cos(a), s=sin(a);
      sr += in[2*n]*c - in[2*n+1]*s; si += in[2*n]*s + in[2*n+1]*c; }
    out[2*k]=sr; out[2*k+1]=si; }
}
static void *ap_alloc(size_t bytes){ void *p=NULL;
  if(posix_memalign(&p,4096,bytes)) { perror("alloc"); exit(1);} return p; }
#endif
