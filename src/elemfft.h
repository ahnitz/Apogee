/* Element-space transform shared by both back ends.
   Width-generic (AP_W), so it serves the AVX-512 and AVX2 paths from one source. */
#ifndef AP_ELEMFFT_H
#define AP_ELEMFFT_H
#include "simd.h"
#include "codelets.h"

/* factor M into two codelet-sized halves; M1 == M means "single codelet" */
/* Element-transform sizes efactor can decompose.  Anything else must be
   rejected at plan time rather than silently mis-transformed: forcing an
   unsupported split used to return an impulse response with error 1.0. */
static inline int esupported(int M){
  switch(M){ case 8: case 16: case 32: case 64:
             case 128: case 256: case 512: case 1024: return 1; }
  return 0;
}

static inline void efactor(int M,int *M1,int *M2){
  switch(M){
    case 1024: *M1=32; *M2=32; break;
    case  512: *M1=32; *M2=16; break;
    case  256: *M1=16; *M2=16; break;
    case  128: *M1=16; *M2=8;  break;
    default:   *M1=M;  *M2=1;  break;     /* 8,16,32,64 */
  }
}
#define ESTRIDE(M1) ((M1)+1)
/* Index maps between natural element order and the padded four-step layout.
   M1/M2 are powers of two, so these must be shifts and masks - a runtime integer
   divide here costs more than the transform stage it indexes into. */
typedef struct { int st, m2mask, m2shift, m1mask, m1shift, single; } emap;
static inline emap emake(int M1,int M2){
  emap e; e.single=(M2==1); e.st=ESTRIDE(M1);
  e.m2mask=M2-1; e.m1mask=M1-1;
  e.m2shift=0; while((1<<e.m2shift)<M2) e.m2shift++;
  e.m1shift=0; while((1<<e.m1shift)<M1) e.m1shift++;
  return e;
}
static inline int eidx(const emap *e,int k){        /* slot holding output element k */
  return e->single ? k : e->st*(k & e->m2mask) + (k >> e->m2shift);
}
static inline int einp(const emap *e,int n){        /* slot to place input element n */
  return e->single ? n : (n & e->m1mask) + e->st*(n >> e->m1shift);
}

/* ---- element-space transform of size M, lanes independent ----------------
   Sizes up to 64 are a single generated codelet.  Larger M is a two-level
   four-step over codelet-sized factors M = M1*M2, with the element stride padded
   to M1+1 so the stride-M1 pass does not collapse onto a couple of L1 sets - the
   same padding that was worth 13x on the specialised path.
   Output element k then lives at EIDX(), not at k: the four-step leaves it
   transposed, and undoing that would cost more than indexing around it.        */
/* Codelet choice, measured per point per butterfly level so the sizes compare
 * fairly (ns/point/level; lower is better):
 *
 *            AVX2 (8 lanes)        AVX-512 (16 lanes)
 *   fft16_44   0.0342                0.0201
 *   fftsr16    0.0300  <- 14%        0.0147  <- 27%
 *   fft32_84   0.0326                0.0170
 *   fftsr32    0.0304  <-  7%        0.0155  <-  9%
 *   fft64_88   0.0357                0.0196
 *   fftsr64    0.154   <- 4.9x WORSE 0.0161  <- 18% better
 *
 * Split-radix wins at 16 and 32 at both widths.  At 64 it depends on the
 * register file: AVX-512 has 32 zmm and the whole DAG stays live, AVX2 has 16
 * ymm and it spills catastrophically.  So 64 is split-radix only at 16 lanes.
 */
static inline int codelet(int m,vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,long S){
  switch(m){
    case  8: return fft8_42 (ar,ai,br,bi,S);
    case 16: return fftsr16 (ar,ai,br,bi,S);
    case 32: return fftsr32 (ar,ai,br,bi,S);
#if AP_W >= 16
    default: return fftsr64 (ar,ai,br,bi,S);
#else
    default: return fft64_88(ar,ai,br,bi,S);
#endif
  }
}
/* Same, but the four-step twiddle is applied to the inputs as they are read.
   The alternative is a standalone pass that re-reads and re-writes the whole
   block purely to multiply it - this removes that pass entirely. */
static inline int codelet_tw(int m,vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,long S,
                             const float*restrict twr,const float*restrict twi){
  switch(m){
    case  8: return fft8_tw (ar,ai,br,bi,S,twr,twi);
    case 16: return fftsr16_tw(ar,ai,br,bi,S,twr,twi);
    case 32: return fftsr32_tw(ar,ai,br,bi,S,twr,twi);
#if AP_W >= 16
    default: return fftsr64_tw(ar,ai,br,bi,S,twr,twi);
#else
    default: return fft64_tw(ar,ai,br,bi,S,twr,twi);
#endif
  }
}
/* itwr/itwi hold W_M[e1*k2p] laid out [k2p][e1], so the second half can consume
   them directly. */
/* Dispatch for the product-loading codelets. */
static inline int codelet_prod(int m,const float*restrict dr,const float*restrict di,
                               const float*restrict tr,const float*restrict ti,
                               vf*restrict ar,vf*restrict ai,vf*restrict br,vf*restrict bi,
                               long S,long DS){
  switch(m){
    case  8: return fft8_prod (dr,di,tr,ti,ar,ai,br,bi,S,DS);
    case 16: return fft16_prod(dr,di,tr,ti,ar,ai,br,bi,S,DS);
    case 32: return fft32_prod(dr,di,tr,ti,ar,ai,br,bi,S,DS);
    default: return fft64_prod(dr,di,tr,ti,ar,ai,br,bi,S,DS);
  }
}

/* Can the product be fused into this element size's first pass?
 *
 * Only when the transform is single-level.  Two-level means the first codelet
 * walks its input with stride M1*AP_W - 2 KiB at 2^18 - where the unfused path
 * reads the source sequentially into a buffer and then reads the buffer.  Trading
 * a sequential read plus a round trip for a strided read loses badly: measured
 * 14% worse at 2^16 and 18% at 2^18 on AVX2.  Below that the source read stays
 * sequential and fusing wins. */
static inline int eprod_ok(int M){
  int M1,M2; efactor(M,&M1,&M2); (void)M1;
  return M2==1;
}

/* Element transform whose first pass forms conj(d*t) as it loads, so the matched
   filter's product never reaches memory and the staging buffer disappears.
   dr/di/tr/ti are group-major: element e of this group sits at e*AP_W floats. */
static void efft_prod(int M,const float*restrict dr,const float*restrict di,
                      const float*restrict tr,const float*restrict ti,
                      vf*restrict X,vf*restrict Xi,vf*restrict S,vf*restrict Si,
                      const float*restrict itwr,const float*restrict itwi){
  int M1,M2; efactor(M,&M1,&M2);
  if(M2==1){ codelet_prod(M,dr,di,tr,ti,X,Xi,S,Si,1,AP_W); return; }
  const int st=ESTRIDE(M1);
  /* element (e2,e1) of the group is at (e2*M1 + e1)*AP_W, so at fixed e1 the
     inner codelet walks e2 with stride M1*AP_W */
  for(int e1=0;e1<M1;e1++)
    codelet_prod(M2,dr+(size_t)e1*AP_W,di+(size_t)e1*AP_W,
                 tr+(size_t)e1*AP_W,ti+(size_t)e1*AP_W,
                 X+e1,Xi+e1,S+e1,Si+e1,st,(long)M1*AP_W);
  for(int k2p=0;k2p<M2;k2p++)
    codelet_tw(M1,X+st*k2p,Xi+st*k2p,S+st*k2p,Si+st*k2p,1,
               itwr+(size_t)k2p*M1, itwi+(size_t)k2p*M1);
}

static void efft(int M,vf*restrict X,vf*restrict Xi,vf*restrict S,vf*restrict Si,
                 const float*restrict itwr,const float*restrict itwi){
  int M1,M2; efactor(M,&M1,&M2);
  if(M2==1){ codelet(M,X,Xi,S,Si,1); return; }
  const int st=ESTRIDE(M1);
  for(int e1=0;e1<M1;e1++) codelet(M2,X+e1,Xi+e1,S+e1,Si+e1,st);
  for(int k2p=0;k2p<M2;k2p++)
    codelet_tw(M1,X+st*k2p,Xi+st*k2p,S+st*k2p,Si+st*k2p,1,
               itwr+(size_t)k2p*M1, itwi+(size_t)k2p*M1);
}

#endif
