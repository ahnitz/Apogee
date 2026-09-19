/* peakfft unit tests: building blocks + exact transform correctness.
   Requires no external FFT library - references are a double-precision O(N^2) DFT
   and closed-form analytic transforms. */
#include <string.h>
#include <immintrin.h>
#include "peakfft.h"
#include "internal.h"
#include "transpose16.h"
#include "codelets.h"
#include "testutil.h"

static void test_transpose16(void){
  float a[16][16], b[16][16]; __m512 in[16], out[16];
  for(int r=0;r<16;r++) for(int c=0;c<16;c++) a[r][c]=(float)(r*16+c);
  for(int r=0;r<16;r++) in[r]=_mm512_loadu_ps(a[r]);
  t16(in,out);
  for(int r=0;r<16;r++) _mm512_storeu_ps(b[r],out[r]);
  int bad=0;
  for(int r=0;r<16;r++) for(int c=0;c<16;c++) if(b[r][c]!=a[c][r]) bad++;
  CHECK(bad==0, "16x16 register transpose: %d mismatched elements", bad);
}

/* run a codelet on 16 independent lanes and compare against a direct DFT */
static void test_codelet(const char *name,int n,
                         int (*fn)(__m512*,__m512*,__m512*,__m512*,const long)){
  static float xr[64][16], xi[64][16];
  __m512 ar[64],ai[64],br[64],bi[64];
  pf_seed(0xC0DEu + n);
  for(int e=0;e<n;e++) for(int l=0;l<16;l++){ xr[e][l]=(float)pf_gauss(); xi[e][l]=(float)pf_gauss(); }
  for(int e=0;e<n;e++){ ar[e]=_mm512_loadu_ps(xr[e]); ai[e]=_mm512_loadu_ps(xi[e]); }
  int f=fn(ar,ai,br,bi,1);
  __m512 *Rr=f?br:ar, *Ri=f?bi:ai;
  double worst=0, scale=0;
  for(int l=0;l<16;l++) for(int k=0;k<n;k++){
    double sr=0,si=0;
    for(int e=0;e<n;e++){ double a=-2.0*M_PI*(double)e*k/n,c=cos(a),s=sin(a);
      sr+=xr[e][l]*c-xi[e][l]*s; si+=xr[e][l]*s+xi[e][l]*c; }
    float gr[16],gi[16]; _mm512_storeu_ps(gr,Rr[k]); _mm512_storeu_ps(gi,Ri[k]);
    double d=hypot(gr[l]-sr,gi[l]-si), m=hypot(sr,si);
    if(d>worst) worst=d;
    if(m>scale) scale=m;
  }
  CHECK_LE(worst/scale, 1e-6, "codelet %s relative error", name);
}

/* codelets must also honour a non-unit element stride */
static void test_codelet_stride(void){
  __m512 ar[32*3],ai[32*3],br[32*3],bi[32*3], cr[32],ci[32],dr[32],di[32];
  pf_seed(7);
  float t[16];
  for(int e=0;e<32;e++){
    for(int l=0;l<16;l++) t[l]=(float)pf_gauss();
    ar[e*3]=cr[e]=_mm512_loadu_ps(t);
    for(int l=0;l<16;l++) t[l]=(float)pf_gauss();
    ai[e*3]=ci[e]=_mm512_loadu_ps(t);
  }
  int f1=fft32_84(ar,ai,br,bi,3);
  int f2=fft32_84(cr,ci,dr,di,1);
  CHECK(f1==f2, "codelet flip differs between strides");
  __m512 *A=f1?br:ar, *Ai=f1?bi:ai, *C=f2?dr:cr, *Ci=f2?di:ci;
  int bad=0;
  for(int e=0;e<32;e++){
    float u[16],v[16],w[16],z[16];
    _mm512_storeu_ps(u,A[e*3]); _mm512_storeu_ps(v,C[e]);
    _mm512_storeu_ps(w,Ai[e*3]); _mm512_storeu_ps(z,Ci[e]);
    for(int l=0;l<16;l++) if(u[l]!=v[l]||w[l]!=z[l]) bad++;
  }
  CHECK(bad==0, "strided codelet differs from unit stride in %d slots", bad);
}

/* the 24-bit split used for the 2^20 intermediate must round-trip */
static void test_quant24(void){
  pf_seed(11);
  double worst_screen=0, worst_full=0;
  for(int trial=0;trial<200;trial++){
    float v[16]; float mx=0;
    for(int i=0;i<16;i++){ v[i]=(float)pf_gauss(); if(fabsf(v[i])>mx)mx=fabsf(v[i]); }
    if(trial==0){ for(int i=0;i<16;i++) v[i]= (i&1)? mx : -mx; }  /* extremes */
    float sc = mx>0? 8388607.0f/mx : 1.f, dq = mx>0? mx/8388607.0f : 1.f;
    __m512 V=_mm512_loadu_ps(v);
    const __m512i CMAX=_mm512_set1_epi32(8388607), CMIN=_mm512_set1_epi32(-8388607);
    __m512i x=_mm512_max_epi32(CMIN,_mm512_min_epi32(CMAX,
                 _mm512_cvtps_epi32(_mm512_mul_ps(V,_mm512_set1_ps(sc)))));
    __m256i hi=_mm512_cvtepi32_epi16(_mm512_srai_epi32(x,8));
    __m128i lo=_mm512_cvtepi32_epi8(_mm512_and_epi32(x,_mm512_set1_epi32(255)));
    __m512 scr=_mm512_mul_ps(_mm512_cvtepi32_ps(_mm512_cvtepi16_epi32(hi)),
                             _mm512_set1_ps(dq*256.0f));
    __m512i H=_mm512_slli_epi32(_mm512_cvtepi16_epi32(hi),8);
    __m512 full=_mm512_mul_ps(_mm512_cvtepi32_ps(
                   _mm512_or_epi32(H,_mm512_cvtepu8_epi32(lo))),_mm512_set1_ps(dq));
    float s[16],fl[16]; _mm512_storeu_ps(s,scr); _mm512_storeu_ps(fl,full);
    for(int i=0;i<16;i++){
      double a=fabs(s[i]-v[i])/mx, b=fabs(fl[i]-v[i])/mx;
      if(a>worst_screen) worst_screen=a;
      if(b>worst_full) worst_full=b;
    }
  }
  CHECK_LE(worst_screen, 1.0/16384, "24-bit split: screening plane (16 bits)");
  CHECK_LE(worst_full,   1.0/2097152, "24-bit split: full reconstruction (24 bits)");
}

static void test_heap(void){
  pf_cand T[8]; int n=0;
  pf_seed(3);
  float v[200]; for(int i=0;i<200;i++) v[i]=(float)pf_u();
  for(int i=0;i<200;i++) pf_push(T,8,&n,v[i],i,v[i],0.f);
  CHECK(n==8, "heap size after 200 pushes = %d, expected 8", n);
  /* the 8 retained must be the 8 largest */
  float srt[200]; memcpy(srt,v,sizeof v);
  for(int a=0;a<8;a++){ int b=a; for(int c=a+1;c<200;c++) if(srt[c]>srt[b])b=c;
    float t=srt[a]; srt[a]=srt[b]; srt[b]=t; }
  for(int a=0;a<8;a++){ int found=0;
    for(int b=0;b<8;b++) if(T[b].mag2==srt[a]) found=1;
    CHECK(found, "heap lost the #%d largest value", a); }
}

/* exact 1024-point transform vs double-precision O(N^2) DFT */
static void test_fft1024_exact(void){
  int N=1024;
  float *in=pf_alloc(N*8), *out=pf_alloc(N*8);
  double *ref=malloc(N*16);
  pf_seed(42);
  for(int i=0;i<N;i++){ in[2*i]=(float)pf_gauss(); in[2*i+1]=(float)pf_gauss(); }
  pf_plan *p=pf_create(N); CHECK(p!=NULL,"pf_create(1024) returned NULL");
  pf_fft(p,in,out);
  pf_ref_dft(in,ref,N);
  double peak=0,worst=0;
  for(int k=0;k<N;k++){ double m=hypot(ref[2*k],ref[2*k+1]); if(m>peak)peak=m; }
  for(int k=0;k<N;k++){ double d=hypot(out[2*k]-ref[2*k],out[2*k+1]-ref[2*k+1]);
                        if(d>worst)worst=d; }
  CHECK_LE(worst/peak, 1e-6, "N=1024 exact FFT vs reference DFT");
  pf_destroy(p); free(in); free(out); free(ref);
}

/* analytic checks that work at any N: impulse, pure tone, DC, Parseval, linearity */
static void test_analytic(size_t N){
  float *in=pf_alloc(N*8), *out=pf_alloc(N*8), *in2=pf_alloc(N*8), *out2=pf_alloc(N*8);
  pf_plan *p=pf_create(N);
  char tag[64];

  /* unit impulse at n0 -> |X[k]| == 1 for all k */
  int n0 = (int)(N/3);
  memset(in,0,N*8); in[2*n0]=1.f;
  pf_fft(p,in,out);
  double worst=0;
  for(size_t k=0;k<N;k++){
    double a=-2.0*M_PI*(double)n0*k/N;
    double d=hypot(out[2*k]-cos(a), out[2*k+1]-sin(a));
    if(d>worst)worst=d;
  }
  snprintf(tag,sizeof tag,"N=%zu impulse response",N);
  CHECK_LE(worst, 1e-5, "%s", tag);

  /* pure tone at integer bin f -> all energy in bin f, value N */
  int f = (int)(N/7);
  for(size_t n=0;n<N;n++){ double a=2.0*M_PI*(double)f*n/N; in[2*n]=(float)cos(a); in[2*n+1]=(float)sin(a); }
  pf_fft(p,in,out);
  double leak=0;
  for(size_t k=0;k<N;k++) if((int)k!=f){ double m=hypot(out[2*k],out[2*k+1]); if(m>leak)leak=m; }
  snprintf(tag,sizeof tag,"N=%zu tone lands in bin %d",N,f);
  CHECK_LE(fabs(hypot(out[2*f],out[2*f+1])-(double)N)/N, 1e-5, "%s (magnitude)", tag);
  CHECK_LE(leak/(double)N, 1e-5, "%s (leakage)", tag);

  /* and pf_topk must report exactly that bin */
  int idx[4]; float rr[4],ii[4];
  int nk=pf_topk(p,in,1,idx,rr,ii);
  CHECK(nk==1 && idx[0]==f, "N=%zu pf_topk on a pure tone gave idx=%d, expected %d",N,nk?idx[0]:-1,f);

  /* Parseval: sum|X|^2 == N * sum|x|^2 */
  pf_seed(N);
  for(size_t n=0;n<N;n++){ in[2*n]=(float)pf_gauss(); in[2*n+1]=(float)pf_gauss(); }
  pf_fft(p,in,out);
  double e_in=0,e_out=0;
  for(size_t n=0;n<N;n++){ e_in += (double)in[2*n]*in[2*n]+(double)in[2*n+1]*in[2*n+1];
                           e_out+= (double)out[2*n]*out[2*n]+(double)out[2*n+1]*out[2*n+1]; }
  snprintf(tag,sizeof tag,"N=%zu Parseval",N);
  CHECK_LE(fabs(e_out-(double)N*e_in)/(N*e_in), 1e-5, "%s", tag);

  /* linearity: F(a+b) == F(a)+F(b) */
  for(size_t n=0;n<N;n++){ in2[2*n]=(float)pf_gauss(); in2[2*n+1]=(float)pf_gauss(); }
  pf_fft(p,in2,out2);
  double scale=0; for(size_t k=0;k<N;k++){ double m=hypot(out[2*k],out[2*k+1]); if(m>scale)scale=m; }
  for(size_t n=0;n<N;n++){ in2[2*n]+=in[2*n]; in2[2*n+1]+=in[2*n+1]; }
  float *sum=pf_alloc(N*8);
  pf_fft(p,in2,sum);
  worst=0;
  for(size_t k=0;k<N;k++){
    double d=hypot(sum[2*k]-(out[2*k]+out2[2*k]), sum[2*k+1]-(out[2*k+1]+out2[2*k+1]));
    if(d>worst)worst=d;
  }
  snprintf(tag,sizeof tag,"N=%zu linearity",N);
  CHECK_LE(worst/scale, 1e-5, "%s", tag);

  pf_destroy(p); free(in); free(out); free(in2); free(out2); free(sum);
}

static void test_api(void){
  CHECK(pf_create(999)==NULL, "pf_create must reject unsupported N");
  CHECK(pf_supported(1024) && pf_supported(1048576), "pf_supported wrong");
  CHECK(!pf_supported(2048), "pf_supported(2048) should be false");
  CHECK(!pf_supported(1u<<21), "pf_supported(2^21) should be false");
  for(int lg=12;lg<=20;lg++) CHECK(pf_supported((size_t)1<<lg),"pf_supported(2^%d) should be true",lg);
  pf_plan *p=pf_create(1024);
  int idx[4]; float rr[4],ii[4];
  float *in=pf_alloc(1024*8); memset(in,0,1024*8); in[0]=1.f;
  CHECK(pf_topk(p,in,0,idx,rr,ii)==0, "pf_topk(K=0) should return 0");
  pf_destroy(p); pf_destroy(NULL); free(in);
}

int main(void){
  printf("peakfft unit tests\n");
  test_transpose16();
  test_codelet("fft32_84 ",32,fft32_84);
  test_codelet("fft32_442",32,fft32_442);
  test_codelet("fft16_44 ",16,fft16_44);
  test_codelet("fft64_88 ",64,fft64_88);
  test_codelet_stride();
  test_quant24();
  test_heap();
  test_fft1024_exact();
  for(int lg=12; lg<=20; lg++) test_analytic((size_t)1<<lg);
  test_analytic(1024);
  test_api();
  return pf_report("test_units");
}
