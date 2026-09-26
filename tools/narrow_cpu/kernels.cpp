// Measurement-only coarse IFFT candidates. Not linked into the library.
// Compile separately for AVX+SSE4.1, AVX2, or AVX-512BW; see run.py.
#include <immintrin.h>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <vector>
#ifndef IBITS
#define IBITS 256
#endif
#if IBITS == 512
using I=__m512i; using F=__m512;
#define IN(name) _mm512_##name
#define FN(name) _mm512_##name
constexpr int QL=32, FL=16;
#elif IBITS == 256
using I=__m256i; using F=__m256;
#define IN(name) _mm256_##name
#define FN(name) _mm256_##name
constexpr int QL=16, FL=8;
#else
using I=__m128i; using F=__m256;
#define IN(name) _mm_##name
#define FN(name) _mm256_##name
constexpr int QL=8, FL=8;
#endif
constexpr int NH=QL/FL;
static inline F loadf(const float*p){return FN(loadu_ps)(p);}
static inline void storef(float*p,F v){FN(storeu_ps)(p,v);}
static inline F setf(float x){return FN(set1_ps)(x);}
static inline F addf(F a,F b){return FN(add_ps)(a,b);}
static inline F subf(F a,F b){return FN(sub_ps)(a,b);}
static inline F mulf(F a,F b){return FN(mul_ps)(a,b);}
static inline F fmadd(F a,F b,F c){
#ifdef __FMA__
 return FN(fmadd_ps)(a,b,c);
#else
 return addf(mulf(a,b),c);
#endif
}
static inline F absf(F a){
#if IBITS==512
 return _mm512_castsi512_ps(_mm512_and_si512(_mm512_castps_si512(a),_mm512_set1_epi32(0x7fffffff)));
#else
 return _mm256_andnot_ps(_mm256_set1_ps(-0.0f),a);
#endif
}
static inline I loadi(const int16_t*p){
#if IBITS==512
 return _mm512_loadu_si512(p);
#else
 #if IBITS==256
 return _mm256_loadu_si256((const I*)p);
#else
 return _mm_loadu_si128((const I*)p);
#endif
#endif
}
static inline void storei(int16_t*p,I a){
#if IBITS==512
 _mm512_storeu_si512(p,a);
#elif IBITS==256
 _mm256_storeu_si256((I*)p,a);
#else
 _mm_storeu_si128((I*)p,a);
#endif
}
static inline I pack(F a,F b){
#if IBITS==512
 I v=_mm512_packs_epi32(_mm512_cvtps_epi32(a),_mm512_cvtps_epi32(b));
 return _mm512_permutexvar_epi64(_mm512_setr_epi64(0,2,4,6,1,3,5,7),v);
#elif IBITS==256
 return _mm256_permute4x64_epi64(_mm256_packs_epi32(_mm256_cvtps_epi32(a),_mm256_cvtps_epi32(b)),0xd8);
#else
 __m256 v=_mm256_castsi256_ps(_mm256_cvtps_epi32(a));
 return _mm_packs_epi32(_mm_castps_si128(_mm256_castps256_ps128(v)),
                       _mm_castps_si128(_mm256_extractf128_ps(v,1)));
#endif
}
static inline void squares(I r,I i,F &a,F &b){
 I lo=IN(unpacklo_epi16)(r,i),hi=IN(unpackhi_epi16)(r,i);
 lo=IN(madd_epi16)(lo,lo);hi=IN(madd_epi16)(hi,hi);
#if IBITS==128
 a=_mm256_insertf128_ps(_mm256_castps128_ps256(_mm_cvtepi32_ps(lo)),_mm_cvtepi32_ps(hi),1);
 b=setf(0);
#else
 a=FN(cvtepi32_ps)(lo);b=FN(cvtepi32_ps)(hi);
#endif
}
// Carry/borrow-isolated 16-bit fields inside 32-bit SIMD words. Same modulo
// results as native epi16 operations; guard bits prevent cross-field traffic.
#if IBITS==512
#define AND _mm512_and_si512
#define OR _mm512_or_si512
#define XOR _mm512_xor_si512
#elif IBITS==256
#define AND _mm256_and_si256
#define OR _mm256_or_si256
#define XOR _mm256_xor_si256
#else
#define AND _mm_and_si128
#define OR _mm_or_si128
#define XOR _mm_xor_si128
#endif
template<bool SWAR> static inline I addi(I a,I b){
 if constexpr(!SWAR) return IN(add_epi16)(a,b);
 I low=IN(set1_epi32)(0x7fff7fff),high=IN(set1_epi32)(int(0x80008000u));
 return XOR(IN(add_epi32)(AND(a,low),AND(b,low)),AND(XOR(a,b),high));
}
template<bool SWAR> static inline I subi(I a,I b){
 if constexpr(!SWAR) return IN(sub_epi16)(a,b);
 I low=IN(set1_epi32)(0x7fff7fff),high=IN(set1_epi32)(int(0x80008000u));
 return XOR(IN(sub_epi32)(OR(a,high),AND(b,low)),AND(XOR(XOR(a,b),high),high));
}
template<bool SWAR> static inline I halfi(I a){
 if constexpr(!SWAR) return IN(srai_epi16)(a,1);
 return OR(AND(IN(srli_epi32)(a,1),IN(set1_epi32)(0x7fff7fff)),AND(a,IN(set1_epi32)(int(0x80008000u))));
}
struct Plan{
 int n,nd,nt,mode,L,ng,shift=0; const float *data=nullptr;
 std::vector<float> hr,hi,pr,pi,fr,fi,ds,hs,decode,wr,wi;
 std::vector<int16_t> qr,qi,qhr,qhi,qdr,qdi,iw,iv;
 std::vector<int> rev;
 Plan(int n_,int nd_,int nt_,int mode_):n(n_),nd(nd_),nt(nt_),mode(mode_),L(mode==5?FL:QL),ng((nt+L-1)/L),
 hr(ng*n*L),hi(hr.size()),pr(n*L),pi(n*L),fr(n*L),fi(n*L),ds(nd),hs(nt),decode(L),wr(n),wi(n),
 qr(n*L),qi(n*L),qhr(hr.size()),qhi(hr.size()),qdr(nd*n),qdi(nd*n),iw(n),iv(n),rev(n){
  int bits=__builtin_ctz(unsigned(n));
  for(int k=0;k<n;k++){
   int j=0;for(int b=0;b<bits;b++)j=(j<<1)|((k>>b)&1);rev[k]=j;
   wr[k]=std::cos(2*M_PI*k/n);wi[k]=std::sin(2*M_PI*k/n);
   iw[k]=int16_t(std::clamp(std::lround(32768.*std::cos(2*M_PI*k/n)),-32767l,32767l));
   iv[k]=int16_t(std::clamp(std::lround(32768.*std::sin(2*M_PI*k/n)),-32767l,32767l));
  }
 }
 void templates(const float*h){
  for(int t=0;t<nt;t++){
   float mx=0;for(int k=0;k<n;k++)mx=std::max(mx,std::abs(h[2*(t*n+k)])+std::abs(h[2*(t*n+k)+1]));
   hs[t]=mx>0?mx/16000.f:1.f;float s=1/hs[t];
   for(int k=0;k<n;k++){
    size_t j=(size_t)(t/L)*n*L+k*L+t%L;
    float r=h[2*(t*n+k)],i=h[2*(t*n+k)+1];hr[j]=r;hi[j]=i;
    if(mode==4||mode==9){qhr[j]=int16_t(std::nearbyint(r*s));qhi[j]=int16_t(std::nearbyint(i*s));}
   }
  }
 }
 void setdata(const float*d){
  data=d;if(mode!=4&&mode!=9)return;
  for(int row=0;row<nd;row++){
   float mx=0;for(int k=0;k<n;k++)mx=std::max(mx,std::abs(d[2*(row*n+k)])+std::abs(d[2*(row*n+k)+1]));
   ds[row]=mx>0?mx/16000.f:1.f;float s=1/ds[row];
   for(int k=0;k<n;k++){qdr[row*n+k]=int16_t(std::nearbyint(d[2*(row*n+k)]*s));qdi[row*n+k]=int16_t(std::nearbyint(d[2*(row*n+k)+1]*s));}
  }
 }
};
template<int MODE> static inline void cmul(Plan&p,I r,I i,int k,I &rr,I &ii){
 if(k==0){rr=r;ii=i;return;}
 if(k==p.n/4){rr=IN(sub_epi16)(IN(set1_epi16)(0),i);ii=r;return;}
 if constexpr(MODE==3||MODE==8){
  I lo=IN(unpacklo_epi16)(r,i),hi=IN(unpackhi_epi16)(r,i);
  I cr=IN(set1_epi32)(int(uint16_t(p.iw[k])|(uint32_t(uint16_t(-p.iv[k]))<<16)));
  I ci=IN(set1_epi32)(int(uint16_t(p.iv[k])|(uint32_t(uint16_t(p.iw[k]))<<16)));
  I rnd=IN(set1_epi32)(16384);
  rr=IN(packs_epi32)(IN(srai_epi32)(IN(add_epi32)(IN(madd_epi16)(lo,cr),rnd),15),IN(srai_epi32)(IN(add_epi32)(IN(madd_epi16)(hi,cr),rnd),15));
  ii=IN(packs_epi32)(IN(srai_epi32)(IN(add_epi32)(IN(madd_epi16)(lo,ci),rnd),15),IN(srai_epi32)(IN(add_epi32)(IN(madd_epi16)(hi,ci),rnd),15));
 }else{
  I wr=IN(set1_epi16)(p.iw[k]),wi=IN(set1_epi16)(p.iv[k]);
  rr=subi<(MODE==2||MODE==7)>(IN(mulhrs_epi16)(r,wr),IN(mulhrs_epi16)(i,wi));
  ii=addi<(MODE==2||MODE==7)>(IN(mulhrs_epi16)(r,wi),IN(mulhrs_epi16)(i,wr));
 }
}
template<int MODE> static inline void bf(Plan&p,I &ar,I &ai,I &br,I &bi,int k){
 I tr,ti;cmul<MODE>(p,br,bi,k,tr,ti);
 I xr=addi<(MODE==2||MODE==7)>(ar,tr),xi=addi<(MODE==2||MODE==7)>(ai,ti);
 br=subi<(MODE==2||MODE==7)>(ar,tr);bi=subi<(MODE==2||MODE==7)>(ai,ti);
 if constexpr(MODE<6){xr=halfi<MODE==2>(xr);xi=halfi<MODE==2>(xi);br=halfi<MODE==2>(br);bi=halfi<MODE==2>(bi);}
 ar=xr;ai=xi;
}
static inline void bff(Plan&p,F &ar,F &ai,F &br,F &bi,int k){
 F tr=br,ti=bi;
 if(k==p.n/4){tr=subf(setf(0),bi);ti=br;}
 else if(k){tr=fmadd(br,setf(p.wr[k]),mulf(bi,setf(-p.wi[k])));ti=fmadd(br,setf(p.wi[k]),mulf(bi,setf(p.wr[k])));}
 F xr=mulf(addf(ar,tr),setf(.5f)),xi=mulf(addf(ai,ti),setf(.5f));
 br=mulf(subf(ar,tr),setf(.5f));bi=mulf(subf(ai,ti),setf(.5f));ar=xr;ai=xi;
}
static inline I l1max(I mx,I r,I i){
 return IN(max_epu16)(mx,IN(add_epi16)(IN(abs_epi16)(r),IN(abs_epi16)(i)));
}
static inline unsigned reduce_max(I mx){
 alignas(64) uint16_t a[QL];storei((int16_t*)a,mx);unsigned m=0;
 for(int j=0;j<QL;j++)m=std::max(m,unsigned(a[j]));return m;
}
template<int MODE> static void transform(Plan&p){
 unsigned maximum=MODE==9?7816:16002; p.shift=0;int sh=0;I peak=IN(set1_epi16)(0);
 auto begin_stage=[&](unsigned limit){sh=0;while((maximum>>sh)+2>limit)sh++;p.shift+=sh;peak=IN(set1_epi16)(0);};
 auto shifted=[&](I x){if constexpr(MODE>=6)return IN(sra_epi16)(x,_mm_cvtsi32_si128(sh));else return x;};
 auto step2=[&](int len){
  int h=len/2,step=p.n/len;
  if constexpr(MODE>=6)begin_stage(16000);
  for(int a=0;a<p.n;a+=len)for(int j=0;j<h;j++){
   int x=(a+j)*p.L,y=x+h*p.L;
   if constexpr(MODE==5){F ar=loadf(&p.fr[x]),ai=loadf(&p.fi[x]),br=loadf(&p.fr[y]),bi=loadf(&p.fi[y]);bff(p,ar,ai,br,bi,j*step);storef(&p.fr[x],ar);storef(&p.fi[x],ai);storef(&p.fr[y],br);storef(&p.fi[y],bi);}
   else{I ar=shifted(loadi(&p.qr[x])),ai=shifted(loadi(&p.qi[x])),br=shifted(loadi(&p.qr[y])),bi=shifted(loadi(&p.qi[y]));bf<MODE>(p,ar,ai,br,bi,j*step);storei(&p.qr[x],ar);storei(&p.qi[x],ai);storei(&p.qr[y],br);storei(&p.qi[y],bi);}
  }
 };
 if constexpr(MODE==0){for(int len=2;len<=p.n;len*=2)step2(len);return;}
 for(int len=4;len<=p.n;len*=4){
  int h=len/4,step=p.n/len;
  if constexpr(MODE>=6)begin_stage(8096);
  for(int a=0;a<p.n;a+=len)for(int j=0;j<h;j++){
   int x[4];for(int q=0;q<4;q++)x[q]=(a+j+q*h)*p.L;
   if constexpr(MODE==5){
    F r[4],i[4];for(int q=0;q<4;q++){r[q]=loadf(&p.fr[x[q]]);i[q]=loadf(&p.fi[x[q]]);}
    bff(p,r[0],i[0],r[1],i[1],2*j*step);bff(p,r[2],i[2],r[3],i[3],2*j*step);
    bff(p,r[0],i[0],r[2],i[2],j*step);bff(p,r[1],i[1],r[3],i[3],(j+h)*step);
    for(int q=0;q<4;q++){storef(&p.fr[x[q]],r[q]);storef(&p.fi[x[q]],i[q]);}
   }else{
    I r[4],i[4];for(int q=0;q<4;q++){r[q]=shifted(loadi(&p.qr[x[q]]));i[q]=shifted(loadi(&p.qi[x[q]]));}
    bf<MODE>(p,r[0],i[0],r[1],i[1],2*j*step);bf<MODE>(p,r[2],i[2],r[3],i[3],2*j*step);
    bf<MODE>(p,r[0],i[0],r[2],i[2],j*step);bf<MODE>(p,r[1],i[1],r[3],i[3],(j+h)*step);
    for(int q=0;q<4;q++){storei(&p.qr[x[q]],r[q]);storei(&p.qi[x[q]],i[q]);if constexpr(MODE>=6)peak=l1max(peak,r[q],i[q]);}
   }
  }
  if constexpr(MODE>=6)maximum=reduce_max(peak);
 }
 if(__builtin_ctz(unsigned(p.n))%2)step2(p.n);
}
template<int MODE> static void run(Plan&p,float*out,int lo,int hi){
 for(int d=0;d<p.nd;d++)for(int g=0;g<p.ng;g++){
  const float *dr=p.data+2*d*p.n,*hr=&p.hr[g*p.n*p.L],*hi_=&p.hi[g*p.n*p.L];
  if constexpr(MODE==4||MODE==9){
   for(int k=0;k<p.n;k++){
    I r=IN(set1_epi16)(p.qdr[d*p.n+k]),i=IN(set1_epi16)(p.qdi[d*p.n+k]);
    I h=loadi(&p.qhr[(g*p.n+k)*p.L]),j=loadi(&p.qhi[(g*p.n+k)*p.L]);
    storei(&p.qr[p.rev[k]*p.L],IN(add_epi16)(IN(mulhrs_epi16)(r,h),IN(mulhrs_epi16)(i,j)));
    storei(&p.qi[p.rev[k]*p.L],IN(sub_epi16)(IN(mulhrs_epi16)(i,h),IN(mulhrs_epi16)(r,j)));
   }
   for(int l=0;l<p.L&&g*p.L+l<p.nt;l++)p.decode[l]=p.ds[d]*p.hs[g*p.L+l]*32768.f*p.n;
  }else if constexpr(MODE==5){
   for(int k=0;k<p.n;k++){
    F r=setf(dr[2*k]),i=setf(dr[2*k+1]),h=loadf(hr+k*p.L),j=loadf(hi_+k*p.L);
    storef(&p.fr[p.rev[k]*p.L],fmadd(r,h,mulf(i,j)));
    storef(&p.fi[p.rev[k]*p.L],fmadd(i,h,mulf(r,subf(setf(0),j))));
   }
  }else{
   F mx[2]={setf(0),setf(0)},scale[2];
   for(int k=0;k<p.n;k++)for(int q=0;q<NH;q++){
    int x=k*p.L+q*FL;F r=setf(dr[2*k]),i=setf(dr[2*k+1]),h=loadf(hr+x),j=loadf(hi_+x);
    F pr=fmadd(r,h,mulf(i,j)),pi=fmadd(i,h,mulf(r,subf(setf(0),j)));
    storef(&p.pr[x],pr);storef(&p.pi[x],pi);mx[q]=FN(max_ps)(mx[q],addf(absf(pr),absf(pi)));
   }
   for(int q=0;q<NH;q++){
    // Zero products map to zero without a division by zero.
    F safe=FN(max_ps)(mx[q],setf(1e-30f));scale[q]=FN(div_ps)(setf(16000),safe);
    storef(&p.decode[q*FL],mulf(safe,setf(float(p.n)/16000)));
   }
   for(int k=0;k<p.n;k++){
    F r[2]={setf(0),setf(0)},i[2]={setf(0),setf(0)};
    for(int q=0;q<NH;q++){int x=k*p.L+q*FL;r[q]=mulf(loadf(&p.pr[x]),scale[q]);i[q]=mulf(loadf(&p.pi[x]),scale[q]);}
    storei(&p.qr[p.rev[k]*p.L],pack(r[0],r[1]));storei(&p.qi[p.rev[k]*p.L],pack(i[0],i[1]));
   }
  }
  transform<MODE>(p);
  if constexpr(MODE>=6){float rescale=std::ldexp(1.f,p.shift)/p.n;for(float &v:p.decode)v*=rescale;}
  F mx[2]={setf(0),setf(0)};
  for(int k=lo;k<hi;k++){
   if constexpr(MODE==5){F r=loadf(&p.fr[k*p.L]),i=loadf(&p.fi[k*p.L]);mx[0]=FN(max_ps)(mx[0],fmadd(r,r,mulf(i,i)));}
   else{F a,b;squares(loadi(&p.qr[k*p.L]),loadi(&p.qi[k*p.L]),a,b);mx[0]=FN(max_ps)(mx[0],a);if constexpr(NH==2)mx[1]=FN(max_ps)(mx[1],b);}
  }
  alignas(64) float m[2*FL];storef(m,mx[0]);storef(m+FL,mx[1]);
  for(int l=0;l<p.L&&g*p.L+l<p.nt;l++){
   int ix=l;
   if constexpr(MODE!=5&&NH==2)ix=(l%8>=4?FL:0)+(l/8)*4+l%4;
   out[d*p.nt+g*p.L+l]=std::sqrt(m[ix])*(MODE==5?float(p.n):p.decode[l]);
  }
 }
}
extern "C" {
void* narrow_create(int n,int nd,int nt,int mode){if(n<64||n>2048||(n&(n-1))||nd<1||nt<1||mode<0||mode>9)return nullptr;try{return new Plan(n,nd,nt,mode);}catch(...){return nullptr;}}
void narrow_destroy(void*p){delete (Plan*)p;}
void narrow_templates(void*p,const float*h){((Plan*)p)->templates(h);}
void narrow_data(void*p,const float*d){((Plan*)p)->setdata(d);}
void narrow_run(void*p,float*out,int lo,int hi){Plan&q=*(Plan*)p;switch(q.mode){case 0:run<0>(q,out,lo,hi);break;case 1:run<1>(q,out,lo,hi);break;case 2:run<2>(q,out,lo,hi);break;case 3:run<3>(q,out,lo,hi);break;case 4:run<4>(q,out,lo,hi);break;case 5:run<5>(q,out,lo,hi);break;case 6:run<6>(q,out,lo,hi);break;case 7:run<7>(q,out,lo,hi);break;case 8:run<8>(q,out,lo,hi);break;case 9:run<9>(q,out,lo,hi);break;}}
int narrow_lanes(){return QL;}
}
#include <chrono>
extern "C" double narrow_bench(void *p,float*out,int lo,int hi,int reps,int ingest){
 Plan&q=*(Plan*)p;auto start=std::chrono::steady_clock::now();
 for(int j=0;j<reps;j++){if(ingest)q.setdata(q.data);narrow_run(p,out,lo,hi);}
 return std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()/reps;
}
extern "C" double reference_bench(void *runptr,void *setptr,void *p,int n,int nd,int nt,
                                  const float *data,void*out,int lo,int hi,int reps,int ingest){
 using Run=int(*)(void*,int,int,int,int,size_t,float,void*,void*,size_t,size_t);
 using Set=int(*)(void*,int,const float*);
 auto start=std::chrono::steady_clock::now();
 for(int j=0;j<reps;j++){
  if(ingest)for(int d=0;d<nd;d++)((Set)setptr)(p,d,data+2*d*n);
  ((Run)runptr)(p,0,nd,0,nt,n,0.f,out,nullptr,lo,hi);
 }
 return std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()/reps;
}
