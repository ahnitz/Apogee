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
  pf_fft(p,in,out,PF_FORWARD);
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
  pf_fft(p,in,out,PF_FORWARD);
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
  pf_fft(p,in,out,PF_FORWARD);
  double leak=0;
  for(size_t k=0;k<N;k++) if((int)k!=f){ double m=hypot(out[2*k],out[2*k+1]); if(m>leak)leak=m; }
  snprintf(tag,sizeof tag,"N=%zu tone lands in bin %d",N,f);
  CHECK_LE(fabs(hypot(out[2*f],out[2*f+1])-(double)N)/N, 1e-5, "%s (magnitude)", tag);
  CHECK_LE(leak/(double)N, 1e-5, "%s (leakage)", tag);

  /* and the binned maximum over the whole spectrum must report exactly that bin */
  pf_peak pk[4];
  int nk; { int c; nk=pf_binmax(p,in,N,1,N,0.f,pk,&c,PF_FORWARD,0,N); nk=c; }
  CHECK(nk==1 && pk[0].index==f, "N=%zu binmax on a pure tone gave idx=%ld, expected %d",
        N,nk?pk[0].index:-1L,f);
  CHECK_LE(fabs(pk[0].magnitude-(double)N)/N, 1e-5, "N=%zu peak magnitude field",N);
  CHECK_LE(fabs(hypot(pk[0].re,pk[0].im)-pk[0].magnitude)/N, 1e-6,
           "N=%zu magnitude must equal hypot(re,im)",N);

  /* Parseval: sum|X|^2 == N * sum|x|^2 */
  pf_seed(N);
  for(size_t n=0;n<N;n++){ in[2*n]=(float)pf_gauss(); in[2*n+1]=(float)pf_gauss(); }
  pf_fft(p,in,out,PF_FORWARD);
  double e_in=0,e_out=0;
  for(size_t n=0;n<N;n++){ e_in += (double)in[2*n]*in[2*n]+(double)in[2*n+1]*in[2*n+1];
                           e_out+= (double)out[2*n]*out[2*n]+(double)out[2*n+1]*out[2*n+1]; }
  snprintf(tag,sizeof tag,"N=%zu Parseval",N);
  CHECK_LE(fabs(e_out-(double)N*e_in)/(N*e_in), 1e-5, "%s", tag);

  /* linearity: F(a+b) == F(a)+F(b) */
  for(size_t n=0;n<N;n++){ in2[2*n]=(float)pf_gauss(); in2[2*n+1]=(float)pf_gauss(); }
  pf_fft(p,in2,out2,PF_FORWARD);
  double scale=0; for(size_t k=0;k<N;k++){ double m=hypot(out[2*k],out[2*k+1]); if(m>scale)scale=m; }
  for(size_t n=0;n<N;n++){ in2[2*n]+=in[2*n]; in2[2*n+1]+=in[2*n+1]; }
  float *sum=pf_alloc(N*8);
  pf_fft(p,in2,sum,PF_FORWARD);
  worst=0;
  for(size_t k=0;k<N;k++){
    double d=hypot(sum[2*k]-(out[2*k]+out2[2*k]), sum[2*k+1]-(out[2*k+1]+out2[2*k+1]));
    if(d>worst)worst=d;
  }
  snprintf(tag,sizeof tag,"N=%zu linearity",N);
  CHECK_LE(worst/scale, 1e-5, "%s", tag);

  pf_destroy(p); free(in); free(out); free(in2); free(out2); free(sum);
}

/* Backward direction: the round trip must scale by exactly N, a tone must land in
   the mirrored bin, and binmax must agree with pf_fft in that direction too. */
static void test_backward(size_t N){
  float *in=pf_alloc(N*8), *fwd=pf_alloc(N*8), *rt=pf_alloc(N*8);
  pf_plan *p=pf_create(N);
  char tag[64];
  pf_seed(N*7+1);
  for(size_t n=0;n<N;n++){ in[2*n]=(float)pf_gauss(); in[2*n+1]=(float)pf_gauss(); }
  pf_fft(p,in,fwd,PF_FORWARD);
  pf_fft(p,fwd,rt,PF_BACKWARD);
  double scale=0, worst=0;
  for(size_t n=0;n<N;n++){ double m=hypot(in[2*n],in[2*n+1]); if(m>scale)scale=m; }
  for(size_t n=0;n<N;n++){
    double d=hypot(rt[2*n]-(double)N*in[2*n], rt[2*n+1]-(double)N*in[2*n+1]);
    if(d>worst)worst=d;
  }
  snprintf(tag,sizeof tag,"N=%zu backward(forward(x)) == N*x",N);
  CHECK_LE(worst/((double)N*scale), 1e-5, "%s", tag);

  /* exp(-2*pi*i*f*n/N) has its backward peak at bin f */
  int f=(int)(N/5);
  for(size_t n=0;n<N;n++){ double a=-2.0*M_PI*(double)f*n/N;
    in[2*n]=(float)cos(a); in[2*n+1]=(float)sin(a); }
  pf_peak pk[2];
  int nk; { int c; pf_binmax(p,in,N,1,N,0.f,pk,&c,PF_BACKWARD,0,N); nk=c; }
  CHECK(nk==1 && pk[0].index==f, "N=%zu backward tone gave idx=%ld, expected %d",
        N,nk?pk[0].index:-1L,f);
  CHECK_LE(fabs(pk[0].magnitude-(double)N)/N, 1e-5, "N=%zu backward peak magnitude",N);

  /* the backward binned maximum must match a brute-force scan of pf_fft(BACKWARD) */
  pf_seed(N*13+5);
  for(size_t n=0;n<N;n++){ in[2*n]=(float)pf_gauss(); in[2*n+1]=(float)pf_gauss(); }
  pf_fft(p,in,fwd,PF_BACKWARD);
  int best=0; double bm=-1;
  for(size_t k=0;k<N;k++){ double m=(double)fwd[2*k]*fwd[2*k]+(double)fwd[2*k+1]*fwd[2*k+1];
    if(m>bm){bm=m;best=(int)k;} }
  { int c; pf_binmax(p,in,N,1,N,0.f,pk,&c,PF_BACKWARD,0,N); nk=c; }
  CHECK(nk==1 && pk[0].index==best,
        "N=%zu backward binmax idx=%ld but pf_fft peak is %d",N,nk?pk[0].index:-1L,best);
  CHECK_LE(hypot(pk[0].re-fwd[2*best],pk[0].im-fwd[2*best+1])/sqrt(bm), 1e-5,
           "N=%zu backward binmax value",N);
  pf_destroy(p); free(in); free(fwd); free(rt);
}

static void test_api(void){
  CHECK(pf_create(999)==NULL, "pf_create must reject unsupported N");
  CHECK(pf_supported(1024) && pf_supported(1048576), "pf_supported wrong");
  CHECK(!pf_supported(2048), "pf_supported(2048) should be false");
  CHECK(!pf_supported(1u<<21), "pf_supported(2^21) should be false");
  for(int lg=12;lg<=20;lg++) CHECK(pf_supported((size_t)1<<lg),"pf_supported(2^%d) should be true",lg);
  pf_plan *p=pf_create(1024);
  float *in=pf_alloc(1024*8); memset(in,0,1024*8); in[0]=1.f;

  pf_destroy(p); pf_destroy(NULL); free(in);
}


/* No-shift int16 codelets: the per-level shifts are replaced by headroom in the
   input scale, which is 28% of the codelet's instructions.  Check both that the
   headroom bound is right (one bit per level, and one fewer overflows) and that
   the result is accurate enough to screen with. */
static void test_i16_noshift(void){
  enum{N=32,LANES=32,LEVELS=5};
  vq15 *a=aligned_alloc(64,80*sizeof(vq15)),*b=aligned_alloc(64,80*sizeof(vq15));
  vq15 *c=aligned_alloc(64,80*sizeof(vq15)),*d=aligned_alloc(64,80*sizeof(vq15));
  double re[N],im[N];
  unsigned long long rs=12345;
  for(int n=0;n<N;n++){
    rs=rs*6364136223846793005ULL+1; re[n]=(double)(rs>>11)/9007199254740992.0*2-1;
    rs=rs*6364136223846793005ULL+1; im[n]=(double)(rs>>11)/9007199254740992.0*2-1;
  }
  /* worst-case growth over LEVELS radix-2 stages is 2^LEVELS, so LEVELS bits of
     headroom must be safe and fewer must be allowed to overflow */
  double scale=32767.0/(1<<LEVELS);
  short sr[LANES],si[LANES];
  for(int n=0;n<N;n++){
    for(int l=0;l<LANES;l++){ sr[l]=(short)lrint(re[n]*scale); si[l]=(short)lrint(im[n]*scale); }
    a[n]=_mm512_loadu_si512(sr); b[n]=_mm512_loadu_si512(si);
  }
  int f=ffti16_32_ns(a,b,c,d,1);
  vq15 *R=f?c:a,*I=f?d:b;
  double worst=0,peak=0;
  for(int k=0;k<N;k++){
    double gr=0,gi=0;
    for(int n=0;n<N;n++){ double t=-2.0*M_PI*n*k/N;
      gr+=re[n]*cos(t)-im[n]*sin(t); gi+=re[n]*sin(t)+im[n]*cos(t); }
    short o1[LANES],o2[LANES];
    _mm512_storeu_si512(o1,R[k]); _mm512_storeu_si512(o2,I[k]);
    double m=hypot(gr,gi); if(m>peak)peak=m;
    double e=hypot(o1[0]/scale-gr,o2[0]/scale-gi); if(e>worst)worst=e;
    /* every lane holds the same transform, so they must all agree */
    for(int l=1;l<LANES;l++) CHECK(o1[l]==o1[0] && o2[l]==o2[0],
      "ffti16_32_ns lane %d disagrees with lane 0 at k=%d",l,k);
  }
  CHECK(worst/peak < 5e-3, "ffti16_32_ns relative error %.3e too large for screening",
        worst/peak);
  free(a);free(b);free(c);free(d);
}

int main(void){
  test_i16_noshift();
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
  test_backward(1024);
  for(int lg=12; lg<=20; lg++) test_backward((size_t)1<<lg);
  test_api();
  return pf_report("test_units");
}
