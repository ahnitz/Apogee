/* matchedfilter: width-generic balanced-split back end.
 *
 * Compiled twice - once at AP_W=16 (AVX-512) and once at AP_W=8 (AVX2) - from the
 * same source, via the operation macros in simd.h.  This is the whole AVX2
 * implementation, and on AVX-512 it doubles as a cross-check of the specialised
 * paths.
 *
 *   N = N1 * N2 with both ~ sqrt(N) and both a multiple of the vector width.
 *   n = n2*N1 + n1                      (n1 contiguous)
 *   stage A: for each n1, DFT over n2 (size N2); lanes = W consecutive n1
 *   twiddle W_N[n1*k2]; intermediate held as inter[n1][k2], fp32
 *   stage B: for each k2, DFT over n1 (size N1); lanes = W consecutive k2
 *   output X[k1*N2 + k2], contiguous in k2
 *
 * Neither stage needs in-register shuffles: the lanes are independent transforms,
 * so every twiddle is a broadcast.  The single corner turn is fused into stage A's
 * store, where a W x W register transpose turns what would be a W-way scatter into
 * one contiguous run.
 */
#include <stdlib.h>
#include <string.h>
#include <math.h>
/* AP_ABLATE removes one piece of the pipeline so its cost can be priced.  Results
   are WRONG when it is non-zero; it exists because estimating where the time goes
   has been wrong here more often than it has been right.
     1 no corner turn   2 no element transform   3 no four-step twiddle
     4 contiguous load  5 no padded index remap  6 stage-A body removed
     7 no intermediate store   8 no twiddle and no corner turn
   What it showed at 2^14: removing any single piece saves nothing, removing all of
   them saves half.  The loop is throughput-limited with its parts overlapping, so
   only total work matters - and the element transform is NOT the cost. */
#ifndef AP_ABLATE
#define AP_ABLATE 0
#endif
/* Compile-time specialisation probe: with AP_FIXED_N1/N2 set, the hot loops see
   constants where they normally read plan fields.  kernel1024.c is fully unrolled
   with compile-time sizes and spends 47% of its time outside the codelets; this
   generic path spends 67% at the same codelet cost, so the question is how much
   of that is runtime indirection. */
#ifdef AP_FIXED_N1
#define PN1 AP_FIXED_N1
#define PN2 AP_FIXED_N2
#else
#define PN1 (p->N1)
#define PN2 (p->N2)
#endif
/* Prefetching the strided loads was measured at every distance from 4 to 32 and
   gained nothing: the hardware prefetcher already handles a constant stride. */
#ifndef AP_PF
#define AP_PF 0
#endif
#include "simd.h"
#include "matchedfilter.h"
#include "backend.h"
#ifdef AP_PROF
#include <time.h>
double ap_pA=0,ap_pB=0,ap_pAfft=0,ap_pAtw=0,ap_pAq=0,ap_pBload=0,ap_pBfft=0,ap_pBscan=0;
static inline double pnow(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return t.tv_sec+1e-9*t.tv_nsec;}
#define PT(x) double x=pnow()
#define PACC(v,x) v+=pnow()-(x)
#else
#define PT(x)
#define PACC(v,x)
#endif
#include "codelets.h"
#include "elemfft.h"

#define CAT2(a,b) a##b
#define CAT(a,b) CAT2(a,b)
#define STR2(x) #x
#define STR(x) STR2(x)
/* Static helpers need distinct names too, for the same reason as the back-end
   struct: several copies of this file end up in one object set. */
#ifdef AP_PORTABLE
#define FN(name) CAT(CAT(pfp,AP_W),_##name)
#else
#define FN(name) CAT(CAT(pfb,AP_W),_##name)
#endif


typedef struct {
  size_t N; int N1,N2;
  /* Intermediate as 24-bit block floating point rather than fp32: a 16-bit plane
     the screening pass reads, plus an 8-bit residual touched only for the columns
     that actually hold a peak.  Cuts the intermediate round trip from 16 bytes per
     complex to 10, which is what decides the large sizes once the working set
     leaves L2.  Layout keeps re and im adjacent so each store is a full line. */
  short *q;            /* [2*(n1*N2 + W*b) + l] = re, +W = im */
  signed char *r8;     /* same indexing, low 8 bits                */
  float *scl;          /* [n1*(N2/W) + b] dequant scale            */
  float *ire,*iim;     /* fp32 intermediate, used when quantising would not pay */
  int gblk;            /* stage-A groups loaded per pass over the input          */
  int bblk;            /* stage-B column blocks loaded per pass over the intermediate */
  int gmajor;          /* 1 = fused-product inputs are stored group-major     */
  int ilay;            /* 1 = intermediate as [k2 block][n1][lane]           */
  vf *bmx,*bre,*bim;   /* per-bin running max, and the winner's value            */
  vi *bix;             /* per-bin block index of the current winner              */
  size_t nbcap;
  size_t bstride;      /* vf elements between group buffers                      */
  size_t istr;         /* intermediate row stride, padded off a power of two      */
  vf *bR,*bI,*sR,*sI;
  vf *TLr,*TLi;
  float *w1r,*w1i,*w2r,*w2i;
  float *hr,*hi,*lr,*li;
  float *scg;          /* [g][k2] scalar part of the stage-A twiddle, precomputed */
  vf *twr,*twi;        /* full twiddle vectors, when they are small enough to hold */
  int fulltw;
  int fuse;     /* fused product in stage A; resolved once at plan build,
                   never per transform -- getenv in stageA_prod_gm cost a
                   library call on every pair. */
  unsigned nmask;
  int a1,a2,b1,b2;      /* codelet factorisation of N1 and N2 */
  emap ea,eb;           /* index maps for those factorisations */
} BP;

int FN(supported)(size_t N){
  /* Powers of two from 256 to 2^20.  The lower bound used to be 4096, which was
     arbitrary - what actually constrains it is that both halves of the split must
     be at least one vector wide.  The hierarchical filter needs the small sizes:
     its coarse pass is an N/R-point transform, and restricting R to keep N/R
     above 4096 would remove most of the tuning range.
     256 is the floor because 2^7 splits 16x8, and 8 is below the AVX-512 lane
     count - the supported set is kept identical across back ends so it does not
     depend on which one the CPU happens to select. */
  if((N&(N-1))||N<256u||N>(1u<<20)) return 0;
  int m=0; while(((size_t)1<<m)<N) m++;
  int n1=1<<((m+1)/2), n2=1<<(m/2);
  /* The balanced split is not always best: what matters is which element sizes
     the two stages land on, because the codelets differ by up to 27% per point
     per level (see codelet() in elemfft.h).  Measured winners, median of 3, on
     both widths - everything not listed measured within noise of balanced:
       2^12  128x32   AVX2 7.1% faster, AVX-512 10.3%
       2^18  1024x256 AVX2 9.1% faster, AVX-512  4.8%
     Compiled in rather than searched: the same two win on both ISAs. */
  if(m==12){ n1=128;  n2=32;  }
  if(m==18){ n1=1024; n2=256; }
  return n1>=AP_W && n2>=AP_W;
}

void *FN(create)(size_t N){
  if(!FN(supported)(N)) return NULL;
  int m=0; while(((size_t)1<<m)<N) m++;
  int n1=1<<((m+1)/2), n2=1<<(m/2);
  /* The balanced split is not always best: what matters is which element sizes
     the two stages land on, because the codelets differ by up to 27% per point
     per level (see codelet() in elemfft.h).  Measured winners, median of 3, on
     both widths - everything not listed measured within noise of balanced:
       2^12  128x32   AVX2 7.1% faster, AVX-512 10.3%
       2^18  1024x256 AVX2 9.1% faster, AVX-512  4.8%
     Compiled in rather than searched: the same two win on both ISAs. */
  if(m==12){ n1=128;  n2=32;  }
  if(m==18){ n1=1024; n2=256; }
  { const char *e=getenv("MF_N1");
    if(e){ int v=atoi(e);
      if(v>=AP_W && v<=(int)(N/AP_W) && !(v&(v-1)) && esupported(v) && esupported((int)(N/v))){
        n1=v; n2=(int)(N/v);
      } } }
  /* The element transform only handles the sizes efactor knows.  A split it
     cannot compute used to be accepted and produce silently wrong answers - an
     impulse came back with error 1.0 - so refuse it instead. */
  if(!esupported(n1) || !esupported(n2)) return NULL;
  BP *p=aligned_alloc(64,sizeof(BP)); if(!p) return NULL;
  memset(p,0,sizeof(BP));
  p->N=N; p->N1=n1; p->N2=n2; p->nmask=(unsigned)(N/AP_W-1);
  efactor(n1,&p->a1,&p->a2); efactor(n2,&p->b1,&p->b2);
  p->ea=emake(p->a1,p->a2); p->eb=emake(p->b1,p->b2);
  int a1,a2,b1,b2; efactor(n1,&a1,&a2); efactor(n2,&b1,&b2);
  size_t s1=(a2==1)?(size_t)n1:(size_t)ESTRIDE(a1)*a2;
  size_t s2=(b2==1)?(size_t)n2:(size_t)ESTRIDE(b1)*b2;
  size_t me=s1>s2?s1:s2;
  /* Quantising trades arithmetic for bytes moved.  It is now OFF at every size.
     It was enabled above 2^17 on the argument that the intermediate no longer fits
     cache, and that held while stage A read the input one group at a time.  Once
     the group blocking widened the input stream, re-measuring with bench/ab (same
     build, only this knob varying) says fp32 wins everywhere:

        2^12 1.32x  2^14 1.39x  2^15 1.41x  2^16 1.34x  2^17 1.33x
        2^18 1.18x  2^19 1.26x  2^20 1.10x      (all slower when quantised,
                                                 0/48 and 0/16 rounds)

     The pack/unpack arithmetic costs more than the 25% of intermediate bytes it
     saves.  Kept behind MF_USEQ because the balance moves with the access
     pattern and this is the second time it has flipped. */
  /* Intermediate row stride.  Padding it off the power of two was tried - the
     element buffers needed exactly that, and ablating the store shows it costing
     13% at 2^12 and 20% at 2^14 - but isolated on one build it measures as noise
     at every size.  The store is simply the cost of writing the intermediate
     (128 KiB at 2^14, ~63 GB/s, which is L2 bandwidth), not set aliasing. */
  p->istr = (size_t)n2;
  {
    { size_t sz=(size_t)n1*p->istr;
      size_t alt=(size_t)(n2/AP_W)*n1*AP_W;        /* [k2 block][n1][lane] */
      if(alt>sz) sz=alt;
      p->ire=aligned_alloc(64,sz*sizeof(float));
      p->iim=aligned_alloc(64,sz*sizeof(float)); }
  }
  /* Stage A walks the input with stride N1*8 bytes and, one group at a time, uses
     only 2*AP_W floats of each row.  Measured on this machine, touching 128 bytes
     per 8 KiB row sustains 7.6 GB/s where a sequential read gets 43.9.  Loading G
     groups per pass widens the touched run to G*128 bytes at no change in total
     bytes read.

     G is NOT sized to keep the group buffers in L2, which is what this code did
     first and which is exactly backwards.  Paired A/B against G=1 (bench/ab,
     16/16 or 0/48 rounds, so none of this is noise):

        2^12   G=2/4/16  3.5-4.7% SLOWER      2^15   G=32   4.8% faster
        2^14   G=4/8/16  4.3-5.6% SLOWER      2^17   G=32   5.5% faster
        2^16   indistinguishable              2^18   G=32   20%  faster
                                              2^20   G=32   20%  faster

     The rule that fits every point is about where the *input* lives, not where the
     group buffers live.  While the input is cache-resident a wider stream buys
     nothing and the extra buffers only cost L2, so G=1.  Once it no longer fits
     L2, the stream shape is worth a fifth of the runtime and G should be as large
     as the split allows.  In between - input in L2 but not small - a moderate G
     wins and a large one loses: 2^16 measured G=4 3.1% faster than G=1 (32/32)
     but G=16 3.2% slower. */
  { size_t g_max=(size_t)n1/AP_W, bytes=N*8;
    size_t g;
    if     (bytes <= (1u<<18)) g = 1;    /* <=256 KiB: already cache-resident */
    else if(bytes <= (1u<<20)) g = 4;    /* <=1 MiB: fits L2, keep buffers small */
    else                       g = 32;   /* beyond L2: the stream shape is what matters */
    if(g>g_max) g=g_max;
    if(g<1) g=1;
    { const char *e=getenv("MF_GBLK"); if(e){ long v=atol(e); if(v>0){ g=(size_t)v; if(g>g_max)g=g_max; } } }
    p->gblk=(int)g; p->bstride=me;
  }
  /* Stage B reads the intermediate at [n1][k2], walking n1 with stride istr while
     using only AP_W floats of each row: 64 bytes out of 4 KiB at 2^20, which is
     the same 7.6 GB/s shape the stage-A blocking was introduced to fix.  Loading
     several column blocks per pass widens the touched run to BB*64 bytes at no
     change in total bytes read.  Same L2 tradeoff, so it is sized the same way. */
  { size_t bmaxn=(size_t)n2/AP_W;
    /* Measured: no gain, 1.02-1.05x worse at 2^18 and 2^20.  Stage B's walk is a
       constant 4 KiB stride, which the hardware prefetcher already handles - the
       stage-A input walk it was modelled on is not equivalent.  Default off; the
       mechanism stays behind MF_BBLK. */
    size_t bb = 1;
    if(bb>bmaxn) bb=bmaxn;
    if(bb<1) bb=1;
    { const char *e=getenv("MF_BBLK"); if(e){ long v=atol(e); if(v>0){ bb=(size_t)v; if(bb>bmaxn)bb=bmaxn; } } }
    p->bblk=(int)bb;
  }
  { const char *e=getenv("MF_GMAJOR"); p->gmajor = e?atoi(e):1; }
  { size_t nbuf = (size_t)p->gblk > (size_t)p->bblk ? (size_t)p->gblk : (size_t)p->bblk;
    p->bR=aligned_alloc(64,me*nbuf*sizeof(vf));
    p->bI=aligned_alloc(64,me*nbuf*sizeof(vf)); }
  p->sR=aligned_alloc(64,me*sizeof(vf)); p->sI=aligned_alloc(64,me*sizeof(vf));
  p->TLr=aligned_alloc(64,(size_t)n2*sizeof(vf)); p->TLi=aligned_alloc(64,(size_t)n2*sizeof(vf));
  for(int k2=0;k2<n2;k2++){
    float tr[AP_W],ti[AP_W];
    for(int l=0;l<AP_W;l++){ double a=-2.0*M_PI*(double)l*k2/(double)N;
      tr[l]=(float)cos(a); ti[l]=(float)sin(a); }
    p->TLr[k2]=V_LOADU(tr); p->TLi[k2]=V_LOADU(ti);
  }
  p->w1r=aligned_alloc(64,(size_t)n1*4); p->w1i=aligned_alloc(64,(size_t)n1*4);
  p->w2r=aligned_alloc(64,(size_t)n2*4); p->w2i=aligned_alloc(64,(size_t)n2*4);
  { int a1,a2; efactor(n1,&a1,&a2);
    for(int k=0;k<(a2==1?1:a2);k++) for(int e=0;e<a1;e++){
      double a=-2.0*M_PI*(double)e*k/n1;
      p->w1r[(size_t)k*a1+e]=(float)cos(a); p->w1i[(size_t)k*a1+e]=(float)sin(a); } }
  { int b1,b2; efactor(n2,&b1,&b2);
    for(int k=0;k<(b2==1?1:b2);k++) for(int e=0;e<b1;e++){
      double a=-2.0*M_PI*(double)e*k/n2;
      p->w2r[(size_t)k*b1+e]=(float)cos(a); p->w2i[(size_t)k*b1+e]=(float)sin(a); } }
  /* The stage-A twiddle used to be rebuilt per element from a two-level table:
     four scalar multiplies and a broadcast, all on the critical path, for ~22% of
     all instructions at small N.  Precompute instead.  The full vector form is
     8N bytes, which is worth it while it stays small; above that keep just the
     scalar part (8N/W bytes) so the large sizes do not pay extra traffic. */
  { size_t g_n=(size_t)n1/AP_W;
    p->scg=aligned_alloc(64,g_n*(size_t)n2*2*sizeof(float)+64);
    /* Precomputing the twiddle as full vectors (8N bytes) instead of keeping just
       the scalar part (8N/W) was a win when it was measured, and is not any more:
       2^12 7.7% slower (1/48 rounds), 2^16 2.5% (0/32), 2^14 and 2^18 neutral.
       The table is extra traffic in a loop that is no longer short of ALU. */
    p->fulltw = 0;
    { const char *e=getenv("MF_FULLTW"); if(e) p->fulltw=atoi(e)?1:0; }
    p->fuse = eprod_ok(p->N2);
    { const char *e=getenv("MF_FUSE"); if(e) p->fuse = atoi(e) ? eprod_ok(p->N2) : 0; }
    if(p->fulltw){
      p->twr=aligned_alloc(64,g_n*(size_t)n2*sizeof(vf));
      p->twi=aligned_alloc(64,g_n*(size_t)n2*sizeof(vf));
    }
  }
  { size_t nhi=(N/AP_W)/256; if(nhi<1) nhi=1; double Nq=(double)(N/AP_W);
    p->hr=aligned_alloc(64,nhi*4+64); p->hi=aligned_alloc(64,nhi*4+64);
    p->lr=aligned_alloc(64,256*4);    p->li=aligned_alloc(64,256*4);
    for(size_t j=0;j<nhi;j++){ double a=-2.0*M_PI*(double)(j*256)/Nq;
      p->hr[j]=(float)cos(a); p->hi[j]=(float)sin(a); }
    for(int j=0;j<256;j++){ double b=-2.0*M_PI*(double)j/Nq;
      p->lr[j]=(float)cos(b); p->li[j]=(float)sin(b); }
  }
  /* fill the precomputed twiddles */
  { unsigned nmask=(unsigned)(N/AP_W-1);
    for(int g=0; g<n1/AP_W; g++) for(int k2=0;k2<n2;k2++){
      unsigned mm=((unsigned)g*(unsigned)k2)&nmask, m1=mm>>8, m0=mm&255;
      float sr=p->hr[m1]*p->lr[m0]-p->hi[m1]*p->li[m0];
      float si=p->hr[m1]*p->li[m0]+p->hi[m1]*p->lr[m0];
      size_t idx=(size_t)g*n2+k2;
      p->scg[2*idx]=sr; p->scg[2*idx+1]=si;
      if(p->fulltw){
        vf SR=V_SET1(sr),SI=V_SET1(si);
        p->twr[idx]=V_FMSUB(SR,p->TLr[k2],V_MUL(SI,p->TLi[k2]));
        p->twi[idx]=V_FMADD(SR,p->TLi[k2],V_MUL(SI,p->TLr[k2]));
      }
    }
  }
  return p;
}

void FN(destroy)(void *vp){
  BP *p=vp; if(!p) return;
  free(p->bmx);free(p->bre);free(p->bim);free(p->bix);
  free(p->ire);free(p->iim);free(p->bR);free(p->bI);free(p->sR);free(p->sI);
  free(p->TLr);free(p->TLi);free(p->w1r);free(p->w1i);free(p->w2r);free(p->w2i);
  free(p->hr);free(p->hi);free(p->lr);free(p->li);
  free(p->scg);free(p->twr);free(p->twi);free(p);
}



/* Per-group work shared by the fp32 and pre-quantised load paths: element
   transform, four-step twiddle, corner turn, and the intermediate store. */
/* Everything after the element transform: four-step twiddle, corner turn and
   the intermediate store.  Split out so the fused-product path can run its own
   transform - which loads the product instead of reading a staging buffer - and
   then share this tail. */
static inline void stageA_tail(BP*p,int g,vf*restrict TR,vf*restrict TI,
                               vf*restrict OR,vf*restrict OI,
                               vf*restrict bR,vf*restrict bI){
  const int N2=PN2; const int N1=PN1; (void)N1;
  vf *restrict RR=bR,*restrict RI=bI;
  for(int b=0;b<N2/AP_W;b++){
    if(p->fulltw){
      const vf *twr=p->twr+(size_t)g*N2+AP_W*b, *twi=p->twi+(size_t)g*N2+AP_W*b;
      for(int t=0;t<AP_W;t++){
        int eb=eidx(&p->eb,AP_W*b+t);
        vf xr=RR[eb],xi=RI[eb];
        TR[t]=V_FMSUB(xr,twr[t],V_MUL(xi,twi[t]));
        TI[t]=V_FMADD(xr,twi[t],V_MUL(xi,twr[t]));
      }
    } else {
      const float *sc=p->scg+2*((size_t)g*N2+AP_W*b);
      for(int t=0;t<AP_W;t++){
        int k2=AP_W*b+t;
        vf SR=V_SET1(sc[2*t]),SI=V_SET1(sc[2*t+1]);
        vf tr=V_FMSUB(SR,p->TLr[k2],V_MUL(SI,p->TLi[k2]));
        vf ti=V_FMADD(SR,p->TLi[k2],V_MUL(SI,p->TLr[k2]));
        int eb=eidx(&p->eb,k2);
        vf xr=RR[eb],xi=RI[eb];
        TR[t]=V_FMSUB(xr,tr,V_MUL(xi,ti));
        TI[t]=V_FMADD(xr,ti,V_MUL(xi,tr));
      }
    }
  #if AP_ABLATE==1            /* no corner turn */
  for(int i=0;i<AP_W;i++){OR[i]=TR[i];OI[i]=TI[i];}
#else
  V_TRANSPOSE(TR,OR); V_TRANSPOSE(TI,OI);
#endif
      /* Streaming these past the cache looked right on paper - the line is dead
         until stage B reads it back, so the read-for-ownership is wasted DRAM
         traffic.  Measured, it is 1.22x to 1.62x SLOWER (0/32 rounds); stage B
         wants the line and the store buffer is not the constraint. */
#if AP_ABLATE!=7
      if(p->ilay){
        float *er=p->ire+(size_t)b*N1*AP_W+(size_t)AP_W*g*AP_W;
        float *ei=p->iim+(size_t)b*N1*AP_W+(size_t)AP_W*g*AP_W;
        for(int i=0;i<AP_W;i++){                    /* one contiguous run */
          V_STOREU(er+(size_t)i*AP_W,OR[i]); V_STOREU(ei+(size_t)i*AP_W,OI[i]);
        }
      } else {
        for(int i=0;i<AP_W;i++){
          size_t off=(size_t)(AP_W*g+i)*p->istr+AP_W*b;
          V_STOREU(p->ire+off,OR[i]); V_STOREU(p->iim+off,OI[i]);
        }
      }
#endif

  }
}

static inline void stageA_body(BP*p,int g,vf*restrict TR,vf*restrict TI,
                               vf*restrict OR,vf*restrict OI,
                               vf*restrict bR,vf*restrict bI){
  efft(PN2,bR,bI,p->sR,p->sI,p->w2r,p->w2i);
  stageA_tail(p,g,TR,TI,OR,OI,bR,bI);
}


/* Stage A from split input.  Identical structure to stageA; only the load
   differs - no v_deint, because the caller already has re and im apart. */
static void stageA_split(BP*p,const float*inr,const float*ini,int conj){
  const int N1=PN1,N2=PN2,NG=N1/AP_W,G=p->gblk;
  const vf sg = conj?V_SIGNMASK():V_ZERO();
  vf TR[AP_W],TI[AP_W],OR[AP_W],OI[AP_W];
  const int M1=p->eb.single?N2:p->b1, M2=p->eb.single?1:p->b2, st=p->eb.st;
  for(int g0=0;g0<NG;g0+=G){
    const int GG = (NG-g0<G)?NG-g0:G;
    for(int e2=0;e2<M2;e2++){
      const float *sr=inr+(size_t)AP_W*g0+(size_t)e2*M1*N1;
      const float *si=ini+(size_t)AP_W*g0+(size_t)e2*M1*N1;
      for(int e1=0;e1<M1;e1++){
        for(int gg=0;gg<GG;gg++){
          vf r=V_LOADU(sr+(size_t)AP_W*gg), i=V_LOADU(si+(size_t)AP_W*gg);
          vf *dR=p->bR+(size_t)gg*p->bstride+(size_t)e2*st;
          vf *dI=p->bI+(size_t)gg*p->bstride+(size_t)e2*st;
          dR[e1]=r; dI[e1]=V_XOR(i,sg);
        }
        sr+=N1; si+=N1;
      }
    }
    for(int gg=0;gg<GG;gg++)
      stageA_body(p,g0+gg,TR,TI,OR,OI,
                  p->bR+(size_t)gg*p->bstride,p->bI+(size_t)gg*p->bstride);
  }
}

/* Stage A over spectra stored GROUP-MAJOR, forming the product on the way in.
 *
 * Normal stage A reads x[n2*N1 + n1]: AP_W contiguous floats, then a jump of N1.
 * That is the shape measured at 7.6 GB/s against 43.9 sequential, and the group
 * blocking only widens the run rather than removing the jump.  When the caller
 * owns the layout - which the matched filter does, since preprocessing is free -
 * the spectrum can be stored as [n1 block][n2][lane] instead, and then one
 * group's entire pass is one sequential run of N2*AP_W floats.
 *
 * Layout: spec[g*N2*AP_W + n2*AP_W + l], n1 = g*AP_W + l. */
static void stageA_prod_gm(BP*p,const float*dr,const float*di,
                           const float*tr,const float*ti){
  const int N1=PN1,N2=PN2,NG=N1/AP_W;
  const int fuse=p->fuse;
  vf TR[AP_W],TI[AP_W],OR[AP_W],OI[AP_W];
  for(int g=0;g<NG;g++){
    const size_t gb=(size_t)g*N2*AP_W;
    /* The product is formed inside the first butterfly rather than written to a
       staging buffer this loop would immediately read back - one round trip
       through L1 per group, removed. */
    if(fuse){
      efft_prod(N2,dr+gb,di+gb,tr+gb,ti+gb,p->bR,p->bI,p->sR,p->sI,p->w2r,p->w2i);
    } else {
      /* form the product into the staging buffer, then transform it */
      const int M1=p->eb.single?N2:p->b1, M2=p->eb.single?1:p->b2, st=p->eb.st;
      for(int e2=0;e2<M2;e2++){
        const size_t o0=gb+(size_t)e2*M1*AP_W;
        const float *ar=dr+o0,*ai=di+o0,*br=tr+o0,*bi=ti+o0;
        vf *dR=p->bR+(size_t)e2*st, *dI=p->bI+(size_t)e2*st;
        for(int e1=0;e1<M1;e1++){
          vf x=V_LOADU(ar), y=V_LOADU(ai), u=V_LOADU(br), v=V_LOADU(bi);
          dR[e1]=V_FMSUB(x,u,V_MUL(y,v));
          dI[e1]=V_FNMSUB(x,v,V_MUL(y,u));
          ar+=AP_W; ai+=AP_W; br+=AP_W; bi+=AP_W;
        }
      }
      efft(N2,p->bR,p->bI,p->sR,p->sI,p->w2r,p->w2i);
    }
    stageA_tail(p,g,TR,TI,OR,OI,p->bR,p->bI);
  }
}

/* Stage A that forms the matched-filter product on the way in.
 *
 * The product of two spectra is otherwise written to memory and read straight
 * back by this very loop - 1 MiB of L2 traffic per pair at 2^16.  Computing it
 * here costs the same four FMAs and touches no intermediate at all.
 * Output is conj(D*T), which is what the backward transform wants. */
static void stageA_prod(BP*p,const float*dr,const float*di,
                        const float*tr,const float*ti){
  const int N1=PN1,N2=PN2,NG=N1/AP_W,G=p->gblk;
  vf TR[AP_W],TI[AP_W],OR[AP_W],OI[AP_W];
  const int M1=p->eb.single?N2:p->b1, M2=p->eb.single?1:p->b2, st=p->eb.st;
  for(int g0=0;g0<NG;g0+=G){
    const int GG = (NG-g0<G)?NG-g0:G;
    for(int e2=0;e2<M2;e2++){
      const size_t off0=(size_t)AP_W*g0+(size_t)e2*M1*N1;
      const float *ar=dr+off0,*ai=di+off0,*br=tr+off0,*bi=ti+off0;
      for(int e1=0;e1<M1;e1++){
        for(int gg=0;gg<GG;gg++){
          const size_t o=(size_t)AP_W*gg;
          vf x=V_LOADU(ar+o), y=V_LOADU(ai+o);
          vf u=V_LOADU(br+o), v=V_LOADU(bi+o);
          vf pr=V_FMSUB(x,u,V_MUL(y,v));
          vf pi=V_FNMSUB(x,v,V_MUL(y,u));     /* conj(product), free here */
          vf *dR=p->bR+(size_t)gg*p->bstride+(size_t)e2*st;
          vf *dI=p->bI+(size_t)gg*p->bstride+(size_t)e2*st;
          dR[e1]=pr; dI[e1]=pi;
        }
        ar+=N1; ai+=N1; br+=N1; bi+=N1;
      }
    }
    for(int gg=0;gg<GG;gg++)
      stageA_body(p,g0+gg,TR,TI,OR,OI,
                  p->bR+(size_t)gg*p->bstride,p->bI+(size_t)gg*p->bstride);
  }
}

static void stageA(BP*p,const float*in,int conj){
  const int N1=PN1,N2=PN2,NG=N1/AP_W,G=p->gblk;
  const vf sg = conj?V_SIGNMASK():V_ZERO();
  vf TR[AP_W],TI[AP_W],OR[AP_W],OI[AP_W];
  const int M1=p->eb.single?N2:p->b1, M2=p->eb.single?1:p->b2, st=p->eb.st;
  for(int g0=0;g0<NG;g0+=G){
    const int GG = (NG-g0<G)?NG-g0:G;
    /* one pass over the rows, filling GG group buffers from each row while the
       line is resident - this is the whole point of the blocking */
    for(int e2=0;e2<M2;e2++){
      const float *sp=in+2*(size_t)AP_W*g0+(size_t)e2*M1*2*N1;
      for(int e1=0;e1<M1;e1++){
        for(int gg=0;gg<GG;gg++){
          vf r,i; v_deint(sp+2*(size_t)AP_W*gg,&r,&i);
          vf *dR=p->bR+(size_t)gg*p->bstride+(size_t)e2*st;
          vf *dI=p->bI+(size_t)gg*p->bstride+(size_t)e2*st;
          dR[e1]=r; dI[e1]=V_XOR(i,sg);
        }
        sp+=2*N1;
      }
    }
#if AP_ABLATE!=6        /* 6 = stage A does nothing past the load */
    for(int gg=0;gg<GG;gg++)
      stageA_body(p,g0+gg,TR,TI,OR,OI,
                  p->bR+(size_t)gg*p->bstride,p->bI+(size_t)gg*p->bstride);
#endif
  }
}

/* Load BB consecutive column blocks in one walk over the intermediate rows, so
   each row contributes BB*AP_W contiguous floats instead of AP_W.  Only the fp32
   intermediate is blocked; the quantised path is off by default. */
static void stageB_load_many(BP*p,int b0,int bb){
  const int N1=PN1;
  const int M1=p->ea.single?N1:p->a1, M2=p->ea.single?1:p->a2, st=p->ea.st;
  for(int e2=0;e2<M2;e2++){
    const float *sr=p->ire+(size_t)e2*M1*p->istr+AP_W*b0;
    const float *si=p->iim+(size_t)e2*M1*p->istr+AP_W*b0;
    for(int e1=0;e1<M1;e1++){
      for(int j=0;j<bb;j++){
        vf *dR=p->bR+(size_t)j*p->bstride+(size_t)e2*st;
        vf *dI=p->bI+(size_t)j*p->bstride+(size_t)e2*st;
        dR[e1]=V_LOADU(sr+(size_t)j*AP_W); dI[e1]=V_LOADU(si+(size_t)j*AP_W);
      }
      sr+=p->istr; si+=p->istr;
    }
  }
}
/* transform the j-th buffer that stageB_load_many filled */
static void stageB_run(BP*p,int j,vf**RR,vf**RI){
  const int N1=PN1;
  vf *bR=p->bR+(size_t)j*p->bstride, *bI=p->bI+(size_t)j*p->bstride;
  efft(N1,bR,bI,p->sR,p->sI,p->w1r,p->w1i);
  *RR=bR; *RI=bI;
}

static void stageB(BP*p,int b,vf**RR,vf**RI,int exact){
  const int N1=PN1; (void)PN2; (void)exact;
  const int M1=p->ea.single?N1:p->a1, M2=p->ea.single?1:p->a2, st=p->ea.st;
  const size_t step = p->ilay ? (size_t)AP_W : p->istr;
  const size_t base = p->ilay ? (size_t)b*N1*AP_W : (size_t)AP_W*b;
  for(int e2=0;e2<M2;e2++){
    const float *sr=p->ire+base+(size_t)e2*M1*step;
    const float *si=p->iim+base+(size_t)e2*M1*step;
    vf *dR=p->bR+(size_t)e2*st, *dI=p->bI+(size_t)e2*st;
    for(int e1=0;e1<M1;e1++){
      dR[e1]=V_LOADU(sr); dI[e1]=V_LOADU(si);
      sr+=step; si+=step;
    }
  }
  efft(N1,p->bR,p->bI,p->sR,p->sI,p->w1r,p->w1i);
  *RR=p->bR; *RI=p->bI;

}

void FN(fft)(void *vp,const float*in,float*out,int conj){
  BP *p=vp; const int N1=PN1,N2=PN2;
  const vf sg = conj?V_SIGNMASK():V_ZERO();
  stageA(p,in,conj);
  for(int b=0;b<N2/AP_W;b++){
    vf *RR,*RI; stageB(p,b,&RR,&RI,1);
    for(int k1=0;k1<N1;k1++){ int e=eidx(&p->ea,k1);
      v_inter(out+2*((size_t)k1*N2+AP_W*b),RR[e],V_XOR(RI[e],sg)); }
  }
}



/* ---- binned maximum -------------------------------------------------------
 * One running maximum per bin, carried as vectors so no horizontal reduction
 * happens inside the loop - each bin is reduced once at the end.  The winning
 * lane's re/im ride along in their own accumulators, which keeps the property
 * that outputs are never written anywhere: the only thing that survives the
 * transform is the per-bin best.
 *
 * Four blends per block instead of the top-K path's compare-and-branch, but they
 * are unconditional, so the cost does not depend on the data and there is no
 * heap, no candidate pool and no final sort.
 */
/* The bin accumulators depend on binsize, which is a call argument, so they are
   grown on demand and kept for later calls rather than sized at plan time. */
static int FN(bins_reserve)(BP*p,size_t nb){
  if(nb<=p->nbcap) return 0;
  free(p->bmx);free(p->bre);free(p->bim);free(p->bix);
  p->bmx=aligned_alloc(64,nb*sizeof(vf)); p->bre=aligned_alloc(64,nb*sizeof(vf));
  p->bim=aligned_alloc(64,nb*sizeof(vf)); p->bix=aligned_alloc(64,nb*sizeof(vi));
  if(!p->bmx||!p->bre||!p->bim||!p->bix){ p->nbcap=0; return -1; }
  p->nbcap=nb; return 0;
}

static void FN(binmax_core)(BP*p,size_t binsize,float thr,ap_peak*out,int conj,
                            size_t ws,size_t we){
  const int N1=PN1,N2=PN2;
  const size_t nb=(we-ws+binsize-1)/binsize;
  const float t2 = thr>0.f ? thr*thr : -1.f;
  const vf NEG=V_SET1(-1.f);
  const unsigned allm=(AP_W==16)?0xFFFFu:0xFFu;
  /* Bin index is (k - ws)/binsize, and a runtime divide is ~20 cycles in a loop
     whose whole body is three instructions.  Bin sizes are powers of two in every
     realistic use, so shift instead and keep the divide only as a fallback. */
  const int bpow = (binsize & (binsize-1)) ? -1 : (int)__builtin_ctzl(binsize);
#define BINOF(k) (bpow>=0 ? (((k)-(long)ws)>>bpow) : (((k)-(long)ws)/(long)binsize))

  /* One bin over the whole window is the common case at the small sizes, and then
     the accumulators live in registers. */
  if(nb==1){
    vf am=V_SET1(t2), arr=V_ZERO(), aii=V_ZERO(); vi axx=VI_SET1(-1);
    const int NBK=N2/AP_W, BB=p->bblk;
    for(int b0=0;b0<NBK;b0+=BB){
     const int bbn=(NBK-b0<BB)?NBK-b0:BB;
     if(bbn>1) stageB_load_many(p,b0,bbn);
     for(int jj=0;jj<bbn;jj++){
      const int b=b0+jj;
      long base=(long)AP_W*b;
      long lo=((long)ws-base-(AP_W-1)+N2-1)/N2, hi=((long)we-1-base)/N2;
      if(lo<0) lo=0;
      if(hi>N1-1) hi=N1-1;
      if(lo>hi) continue;
      vf *RR,*RI;
      if(bbn>1) stageB_run(p,jj,&RR,&RI); else stageB(p,b,&RR,&RI,1);
      for(long k1=lo;k1<=hi;k1++){
        int e=eidx(&p->ea,(int)k1);
        long k0=k1*N2+base;
        unsigned inw=allm;
        if(k0<(long)ws || k0+AP_W>(long)we){
          inw=0;
          for(int l=0;l<AP_W;l++){ long k=k0+l;
            if(k>=(long)ws && k<(long)we) inw|=1u<<l; }
          if(!inw) continue;
        }
        vf m2=V_FMADD(RR[e],RR[e],V_MUL(RI[e],RI[e]));
        if(inw!=allm) m2=V_BLENDM(inw,NEG,m2);
        unsigned g=V_GT_MASK(m2,am);
        if(__builtin_expect(g!=0,0)){
          am =V_BLENDM(g,am,m2);
          arr=V_BLENDM(g,arr,RR[e]);
          aii=V_BLENDM(g,aii,RI[e]);
          axx=VI_BLENDM(g,axx,VI_SET1((int)k0));
        }
      }
     }
    }
    float mv[AP_W],rv[AP_W],iv[AP_W]; int xv[AP_W];
    V_STOREU(mv,am); V_STOREU(rv,arr); V_STOREU(iv,aii); VI_STOREU(xv,axx);
    int bl=-1;
    for(int l=0;l<AP_W;l++) if(xv[l]>=0 && (bl<0 || mv[l]>mv[bl])) bl=l;
    if(bl<0){ out[0].index=-1; out[0].re=0.f; out[0].im=0.f; out[0].magnitude=0.f; }
    else { out[0].index=(long)xv[bl]+bl; out[0].re=rv[bl];
           out[0].im=conj?-iv[bl]:iv[bl]; out[0].magnitude=sqrtf(mv[bl]); }
    return;
  }

  /* Many bins: keep only a SCALAR running maximum per bin and compare against a
     broadcast of it.  The obvious form - a vector accumulator per bin - has to
     load 64 bytes per block just to run the compare, which at 2^20 is 4 MiB of
     loads and made this slower than the top-K scan it replaces.  A scalar costs
     4 bytes, and the horizontal reduction needed to update it only runs when a
     block actually beats the bin's best, which the detection floor makes rare. */
  float *bmax=(float*)p->bmx;
  for(size_t j=0;j<nb;j++){
    bmax[j]=t2;
    out[j].index=-1; out[j].re=0.f; out[j].im=0.f; out[j].magnitude=0.f;
  }
  const int NBK2=N2/AP_W, BB2=p->bblk;
  for(int b0=0;b0<NBK2;b0+=BB2){
   const int bbn=(NBK2-b0<BB2)?NBK2-b0:BB2;
   if(bbn>1) stageB_load_many(p,b0,bbn);
   for(int jj=0;jj<bbn;jj++){
    const int b=b0+jj;
    long base=(long)AP_W*b;
    long lo=((long)ws-base-(AP_W-1)+N2-1)/N2, hi=((long)we-1-base)/N2;
    if(lo<0) lo=0;
    if(hi>N1-1) hi=N1-1;
    if(lo>hi) continue;
    vf *RR,*RI;
    if(bbn>1) stageB_run(p,jj,&RR,&RI); else stageB(p,b,&RR,&RI,1);
    for(long k1=lo;k1<=hi;k1++){
      int e=eidx(&p->ea,(int)k1);
      long k0=k1*N2+base;
      unsigned inw=allm;
      if(k0<(long)ws || k0+AP_W>(long)we){
        inw=0;
        for(int l=0;l<AP_W;l++){ long k=k0+l;
          if(k>=(long)ws && k<(long)we) inw|=1u<<l; }
        if(!inw) continue;
      }
      long j0=BINOF(k0), j1=BINOF(k0+AP_W-1);
      vf m2=V_FMADD(RR[e],RR[e],V_MUL(RI[e],RI[e]));
      if(inw!=allm) m2=V_BLENDM(inw,NEG,m2);
      if(j0==j1){
        if(__builtin_expect(V_GT_MASK(m2,V_SET1(bmax[j0]))!=0,0)){
          float mv[AP_W],rv[AP_W],iv[AP_W];
          V_STOREU(mv,m2); V_STOREU(rv,RR[e]); V_STOREU(iv,RI[e]);
          for(int l=0;l<AP_W;l++) if(mv[l]>bmax[j0]){
            bmax[j0]=mv[l];
            out[j0].index=k0+l; out[j0].re=rv[l];
            out[j0].im=conj?-iv[l]:iv[l]; out[j0].magnitude=mv[l];
          }
        }
      } else {
        float mv[AP_W],rv[AP_W],iv[AP_W];
        V_STOREU(mv,m2); V_STOREU(rv,RR[e]); V_STOREU(iv,RI[e]);
        for(int l=0;l<AP_W;l++){
          if(!((inw>>l)&1u)) continue;
          long j=BINOF(k0+l);
          if(mv[l]>bmax[j]){
            bmax[j]=mv[l];
            out[j].index=k0+l; out[j].re=rv[l];
            out[j].im=conj?-iv[l]:iv[l]; out[j].magnitude=mv[l];
          }
        }
      }
    }
   }
  }
  /* magnitude carried squared to keep the hot loop free of sqrt */
  for(size_t j=0;j<nb;j++) if(out[j].index>=0) out[j].magnitude=sqrtf(out[j].magnitude);
#undef BINOF
}

int FN(binmax)(void *vp,const float*in,size_t binsize,float thr,ap_peak*out,
               int conj,size_t ws,size_t we){
  BP *p=vp;
  size_t nb=(we-ws+binsize-1)/binsize;
  if(FN(bins_reserve)(p,nb)) return -1;
  stageA(p,in,conj);
  FN(binmax_core)(p,binsize,thr,out,conj,ws,we);
  return 0;
}

int FN(has_prod)(void *vp){ (void)vp; return 1; }   /* every length here is fused */

int FN(split)(void *vp,int *n1,int *n2){
  BP *p=vp; *n1=p->N1; *n2=p->N2; return 1;
}

int FN(binmax_prod)(void *vp,const float*dr,const float*di,
                    const float*tr,const float*ti,size_t binsize,
                    float thr,ap_peak*out,int conj,size_t ws,size_t we){
  BP *p=vp;
  size_t nb=(we-ws+binsize-1)/binsize;
  if(FN(bins_reserve)(p,nb)) return -1;
  if(p->gmajor) stageA_prod_gm(p,dr,di,tr,ti);
  else          stageA_prod(p,dr,di,tr,ti);
  FN(binmax_core)(p,binsize,thr,out,conj,ws,we);
  return 0;
}

int FN(binmax_split)(void *vp,const float*inr,const float*ini,size_t binsize,
                     float thr,ap_peak*out,int conj,size_t ws,size_t we){
  BP *p=vp;
  size_t nb=(we-ws+binsize-1)/binsize;
  if(FN(bins_reserve)(p,nb)) return -1;
  stageA_split(p,inr,ini,0);     /* caller already folded any input conjugation */
  FN(binmax_core)(p,binsize,thr,out,conj,ws,we);
  return 0;
}



/* The back end this translation unit provides.  The same source is compiled
   several times -- at two widths, and with or without AP_PORTABLE -- so the
   symbol name has to carry which one this is, or the copies collide at link
   time.  Building the portable variant alongside the intrinsic one is what
   lets them be compared inside a single process. */
#ifdef AP_PORTABLE
const ap_backend CAT(ap_be_port,AP_W) = {
  "portable" STR(AP_W),
#else
const ap_backend CAT(ap_be_bal,AP_W) = {
#if AP_W==16
  "balanced-avx512",
#else
  "avx2",
#endif
#endif
  FN(create), FN(destroy), FN(fft), FN(supported),
  FN(binmax), FN(binmax_split), FN(has_prod), FN(split), FN(binmax_prod)
};
