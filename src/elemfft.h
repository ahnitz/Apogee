/* Element-space transform shared by both back ends.
   Width-generic (PF_W), so it serves the AVX-512 and AVX2 paths from one source. */
#ifndef PF_ELEMFFT_H
#define PF_ELEMFFT_H
#include "simd.h"
#include "codelets.h"

/* factor M into two codelet-sized halves; M1 == M means "single codelet" */
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
static inline int codelet(int m,vf*ar,vf*ai,vf*br,vf*bi,long S){
  switch(m){
    case  8: return fft8_42 (ar,ai,br,bi,S);
    case 16: return fftsr16 (ar,ai,br,bi,S);   /* split-radix: 1.4-1.5x the Stockham form here */
    case 32: return fft32_84(ar,ai,br,bi,S);
    default: return fft64_88(ar,ai,br,bi,S);
  }
}
/* Same, but the four-step twiddle is applied to the inputs as they are read.
   The alternative is a standalone pass that re-reads and re-writes the whole
   block purely to multiply it - this removes that pass entirely. */
static inline int codelet_tw(int m,vf*ar,vf*ai,vf*br,vf*bi,long S,
                             const float*twr,const float*twi){
  switch(m){
    case  8: return fft8_tw (ar,ai,br,bi,S,twr,twi);
    case 16: return fftsr16_tw(ar,ai,br,bi,S,twr,twi);
    case 32: return fft32_tw(ar,ai,br,bi,S,twr,twi);
    default: return fft64_tw(ar,ai,br,bi,S,twr,twi);
  }
}
/* itwr/itwi hold W_M[e1*k2p] laid out [k2p][e1], so the second half can consume
   them directly. */
static void efft(int M,vf*X,vf*Xi,vf*S,vf*Si,const float*itwr,const float*itwi){
  int M1,M2; efactor(M,&M1,&M2);
  if(M2==1){ codelet(M,X,Xi,S,Si,1); return; }
  const int st=ESTRIDE(M1);
  for(int e1=0;e1<M1;e1++) codelet(M2,X+e1,Xi+e1,S+e1,Si+e1,st);
  for(int k2p=0;k2p<M2;k2p++)
    codelet_tw(M1,X+st*k2p,Xi+st*k2p,S+st*k2p,Si+st*k2p,1,
               itwr+(size_t)k2p*M1, itwi+(size_t)k2p*M1);
}

#endif
