// Measurement-only AVX (no AVX2) common-exponent SWAR.
// Three signed fields in each FP64 mantissa; twelve values per YMM.
#include <immintrin.h>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include <random>
#include <chrono>
#include <algorithm>
#include <cassert>
constexpr double C=4503599627370496., B=131072., bias=16384.;
constexpr double P=bias*(1.+B+B*B);
static __m256d splat(double x){return _mm256_set1_pd(x);}
static __m256d mask(uint64_t x){double d;std::memcpy(&d,&x,8);return splat(d);}
static __m256d average(__m256d x){
    x=_mm256_and_pd(x,mask(~((1ull<<0)|(1ull<<17)|(1ull<<34))));
    return _mm256_add_pd(_mm256_mul_pd(x,splat(.5)),splat(C*.5));
}
static void butterfly(__m256d a,__m256d b,__m256d& s,__m256d& d,bool scaled){
    if(!scaled){s=_mm256_add_pd(a,_mm256_sub_pd(b,splat(C+P)));d=_mm256_add_pd(a,_mm256_sub_pd(splat(C+P),b));return;}
    s=average(_mm256_add_pd(a,_mm256_sub_pd(b,splat(C))));
    d=average(_mm256_add_pd(a,_mm256_sub_pd(splat(C+2*P),b)));
}
static __m256d field(__m256d x,int j){
    auto v=_mm256_or_pd(_mm256_and_pd(x,mask(0x1ffffull<<(17*j))),splat(C));
    return _mm256_sub_pd(_mm256_mul_pd(_mm256_sub_pd(v,splat(C)),splat(std::ldexp(1.,-17*j))),splat(bias));
}
static __m256d pack(__m256d x,__m256d y,__m256d z){
    return _mm256_add_pd(splat(C+P),_mm256_add_pd(x,_mm256_add_pd(_mm256_mul_pd(y,splat(B)),_mm256_mul_pd(z,splat(B*B)))));
}
static __m256d qround(__m256d x){
    return _mm256_round_pd(_mm256_mul_pd(_mm256_add_pd(x,splat(16384.)),splat(1./32768.)),_MM_FROUND_TO_NEG_INF|_MM_FROUND_NO_EXC);
}
static void rotate(__m256d& r,__m256d& i){
    __m256d rr[3],ii[3];
    for(int j=0;j<3;++j){auto a=field(r,j),b=field(i,j);
        rr[j]=qround(_mm256_sub_pd(_mm256_mul_pd(a,splat(23170.)),_mm256_mul_pd(b,splat(23170.))));
        ii[j]=qround(_mm256_add_pd(_mm256_mul_pd(a,splat(23170.)),_mm256_mul_pd(b,splat(23170.))));}
    r=pack(rr[0],rr[1],rr[2]);i=pack(ii[0],ii[1],ii[2]);
}
static void rotate128(__m128i& r,__m128i& i){
    auto lo=_mm_unpacklo_epi16(r,i),hi=_mm_unpackhi_epi16(r,i);
    auto cr=_mm_set1_epi32((uint32_t(uint16_t(-23170))<<16)|23170),ci=_mm_set1_epi32((23170<<16)|23170);
    auto round=[](__m128i x){return _mm_srai_epi32(_mm_add_epi32(x,_mm_set1_epi32(16384)),15);};
    r=_mm_packs_epi32(round(_mm_madd_epi16(lo,cr)),round(_mm_madd_epi16(hi,cr)));
    i=_mm_packs_epi32(round(_mm_madd_epi16(lo,ci)),round(_mm_madd_epi16(hi,ci)));
}
extern "C" __attribute__((noinline)) void packed_kernel(const double* a,const double* b,double* o,int n,bool twiddle,bool scaled){
    // Per block: r then i; output sum r/i then difference r/i.
    for(int k=0;k<n;k+=8){auto ar=_mm256_loadu_pd(a+k),ai=_mm256_loadu_pd(a+k+4);
        auto br=_mm256_loadu_pd(b+k),bi=_mm256_loadu_pd(b+k+4);if(twiddle)rotate(br,bi);
        __m256d sr,si,dr,di;butterfly(ar,br,sr,dr,scaled);butterfly(ai,bi,si,di,scaled);
        _mm256_storeu_pd(o+2*k,sr);_mm256_storeu_pd(o+2*k+4,si);
        _mm256_storeu_pd(o+2*k+8,dr);_mm256_storeu_pd(o+2*k+12,di);}
}
extern "C" __attribute__((noinline)) void native_kernel(const int16_t* a,const int16_t* b,int16_t* o,int n,bool twiddle,bool scaled){
    auto scale=[&](__m128i x){return scaled?_mm_srai_epi16(x,1):x;};
    for(int k=0;k<n;k+=16){auto ar=_mm_loadu_si128((const __m128i*)(a+k)),ai=_mm_loadu_si128((const __m128i*)(a+k+8));
        auto br=_mm_loadu_si128((const __m128i*)(b+k)),bi=_mm_loadu_si128((const __m128i*)(b+k+8));if(twiddle)rotate128(br,bi);
        _mm_storeu_si128((__m128i*)(o+2*k),scale(_mm_add_epi16(ar,br)));
        _mm_storeu_si128((__m128i*)(o+2*k+8),scale(_mm_add_epi16(ai,bi)));
        _mm_storeu_si128((__m128i*)(o+2*k+16),scale(_mm_sub_epi16(ar,br)));
        _mm_storeu_si128((__m128i*)(o+2*k+24),scale(_mm_sub_epi16(ai,bi)));}
}
static double encode(const int16_t* x){return C+P+x[0]+B*x[1]+B*B*x[2];}
static int decode(double x,int j){return int((uint64_t(x-C)>>(17*j))&0x1ffff)-16384;}
int main(){
    constexpr int pairs=1536,reps=20000;
    std::mt19937 gen(73917);std::uniform_int_distribution<int> dist(-6000,6000);
    std::vector<int16_t> ar(pairs),ai(pairs),br(pairs),bi(pairs),a(2*pairs),b(2*pairs),out(4*pairs);
    std::vector<double> pa(2*pairs/3),pb(2*pairs/3),po(4*pairs/3);
    // Shared L1 bound <=16000 keeps both rotated fields within the bias range.
    for(int j=0;j<pairs;++j){ar[j]=dist(gen);ai[j]=dist(gen);br[j]=dist(gen);bi[j]=dist(gen);}
    // Carry/borrow boundaries, exact odd/even and sign extremes.
    const int16_t edge[]={-8000,-7999,-1,0,1,7999,8000};
    for(int j=0;j<49;++j){ar[j]=edge[j%7];br[j]=edge[j/7];ai[j]=bi[j]=0;}
    for(int k=0;k<pairs;k+=8)for(int j=0;j<8;++j){a[2*k+j]=ar[k+j];a[2*k+8+j]=ai[k+j];b[2*k+j]=br[k+j];b[2*k+8+j]=bi[k+j];}
    for(int k=0;k<pairs;k+=12)for(int j=0;j<4;++j){pa[2*k/3+j]=encode(&ar[k+3*j]);pa[2*k/3+4+j]=encode(&ai[k+3*j]);pb[2*k/3+j]=encode(&br[k+3*j]);pb[2*k/3+4+j]=encode(&bi[k+3*j]);}
    std::puts("{\"pairs\":1536,\"repetitions\":20000,\"results\":[");
    for(int scaled=0;scaled<2;++scaled)for(int tw=0;tw<2;++tw){
        packed_kernel(pa.data(),pb.data(),po.data(),pa.size(),tw,scaled);native_kernel(a.data(),b.data(),out.data(),a.size(),tw,scaled);
        for(int k=0;k<pairs;++k)for(int component=0;component<4;++component){
            int got=decode(po[(k/12)*16+component*4+(k%12)/3],k%3);
            int native=out[(k/8)*32+component*8+k%8];
            int r=br[k],i=bi[k];if(tw){r=int(std::floor(((br[k]-bi[k])*23170.+16384.)/32768.));i=int(std::floor(((br[k]+bi[k])*23170.+16384.)/32768.));}
            int expected=int(std::floor(((component%2?ai[k]:ar[k])+(component<2?1:-1)*(component%2?i:r))/(scaled?2.:1.)));
            if(got!=expected||native!=expected){std::fprintf(stderr,"mismatch %d %d: %d %d %d\n",k,component,got,native,expected);return 1;}}
        std::vector<double> ptime,ntime;
        auto measure=[&](bool packed){auto start=std::chrono::steady_clock::now();for(int it=0;it<reps;++it){
            if(packed)packed_kernel(pa.data(),pb.data(),po.data(),pa.size(),tw,scaled);else native_kernel(a.data(),b.data(),out.data(),a.size(),tw,scaled);
            asm volatile("" ::: "memory");}
            return std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/(reps*pairs);};
        for(int rd=0;rd<9;++rd){if(rd%2){ptime.push_back(measure(true));ntime.push_back(measure(false));}else{ntime.push_back(measure(false));ptime.push_back(measure(true));}}
        std::sort(ptime.begin(),ptime.end());std::sort(ntime.begin(),ntime.end());
        std::printf("%s{\"scaled\":%s,\"twiddle\":%s,\"packed_ns_per_pair\":%.6f,\"native_ns_per_pair\":%.6f,\"speedup\":%.6f,\"exact\":true}",(tw||scaled)?",\n":"",scaled?"true":"false",tw?"true":"false",ptime[4],ntime[4],ntime[4]/ptime[4]);
    }
    std::puts("\n]}");
}
