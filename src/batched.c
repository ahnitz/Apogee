/* peakfft: batched transform.
 *
 * The four-step corner turn in the single-transform path exists for one reason: to
 * manufacture SIMD lanes inside one transform.  Given a batch, the lanes are the
 * batch index instead, so BOTH stages become plain element-space transforms with
 * contiguous loads and **no transposes at all**.
 *
 * Layout is batch-interleaved: element n of transform b lives at in[2*(n*B + b)].
 * A lane load is then one contiguous 2W-float read, and the producer can write this
 * form directly.
 *
 *   n = n2*N1 + n1
 *   stage A: for each n1, DFT over n2 (size N2)   -> inter[(k2*N1 + n1)*B + b]
 *   twiddle W_N[n1*k2]  (scalar per (n1,k2), broadcast - no lane dependence!)
 *   stage B: for each k2, DFT over n1 (size N1)   -> X[k1*N2 + k2]
 *
 * The twiddle losing its lane dependence is the second win: in the single-transform
 * path it varied across lanes and needed a table of vectors.
 */
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "simd.h"
#include "peakfft.h"
#include "backend.h"
#include "codelets.h"
#include "elemfft.h"

struct PBAT {
  size_t N; int N1,N2,B;
  float *ire,*iim;          /* intermediate, split re/im, [k2][n1][batch] */
  vf *bR,*bI,*sR,*sI;       /* element buffers */
  float *w1r,*w1i,*w2r,*w2i;/* per-level twiddles for efft */
  float *tr,*ti;            /* outer four-step twiddle W_N[n1*k2], scalar */
  emap ea,eb; int a1,a2,b1,b2;
};

void *pfbat_create(size_t N,int B){
  int m=0; while(((size_t)1<<m)<N) m++;
  int n1=1<<((m+1)/2), n2=1<<(m/2);
  if(n1<8||n2<8||B%PF_W) return NULL;
  struct PBAT *p=aligned_alloc(64,sizeof(*p)); if(!p) return NULL;
  memset(p,0,sizeof(*p));
  p->N=N; p->N1=n1; p->N2=n2; p->B=B;
  efactor(n1,&p->a1,&p->a2); efactor(n2,&p->b1,&p->b2);
  p->ea=emake(p->a1,p->a2); p->eb=emake(p->b1,p->b2);
  size_t s1=(p->a2==1)?(size_t)n1:(size_t)ESTRIDE(p->a1)*p->a2;
  size_t s2=(p->b2==1)?(size_t)n2:(size_t)ESTRIDE(p->b1)*p->b2;
  size_t me=s1>s2?s1:s2;
  p->ire=aligned_alloc(64,N*(size_t)B*sizeof(float));
  p->iim=aligned_alloc(64,N*(size_t)B*sizeof(float));
  p->bR=aligned_alloc(64,me*sizeof(vf)); p->bI=aligned_alloc(64,me*sizeof(vf));
  p->sR=aligned_alloc(64,me*sizeof(vf)); p->sI=aligned_alloc(64,me*sizeof(vf));
  p->w1r=aligned_alloc(64,(size_t)n1*4); p->w1i=aligned_alloc(64,(size_t)n1*4);
  p->w2r=aligned_alloc(64,(size_t)n2*4); p->w2i=aligned_alloc(64,(size_t)n2*4);
  { int k,e;
    for(k=0;k<(p->a2==1?1:p->a2);k++) for(e=0;e<p->a1;e++){
      double a=-2.0*M_PI*(double)e*k/n1;
      p->w1r[(size_t)k*p->a1+e]=(float)cos(a); p->w1i[(size_t)k*p->a1+e]=(float)sin(a); }
    for(k=0;k<(p->b2==1?1:p->b2);k++) for(e=0;e<p->b1;e++){
      double a=-2.0*M_PI*(double)e*k/n2;
      p->w2r[(size_t)k*p->b1+e]=(float)cos(a); p->w2i[(size_t)k*p->b1+e]=(float)sin(a); } }
  p->tr=aligned_alloc(64,(size_t)n1*n2*4); p->ti=aligned_alloc(64,(size_t)n1*n2*4);
  for(int a=0;a<n1;a++) for(int k=0;k<n2;k++){
    double t=-2.0*M_PI*(double)a*k/(double)N;
    p->tr[(size_t)a*n2+k]=(float)cos(t); p->ti[(size_t)a*n2+k]=(float)sin(t); }
  if(!p->ire||!p->iim||!p->bR||!p->tr){ return NULL; }
  return p;
}
void pfbat_destroy(void *vp){
  struct PBAT *p=vp; if(!p) return;
  free(p->ire);free(p->iim);free(p->bR);free(p->bI);free(p->sR);free(p->sI);
  free(p->w1r);free(p->w1i);free(p->w2r);free(p->w2i);free(p->tr);free(p->ti);free(p);
}

/* one group of PF_W consecutive transforms */
static void stageA_bat(struct PBAT *p,const float *in,int g,int conj){
  const int N1=p->N1,N2=p->N2,B=p->B;
  const vf sg = conj?V_SIGNMASK():V_ZERO();
  for(int n1=0;n1<N1;n1++){
    const float *src=in+2*((size_t)n1*B+(size_t)PF_W*g);
    { const int M1=p->eb.single?N2:p->b1, M2=p->eb.single?1:p->b2, st=p->eb.st;
      for(int e2=0;e2<M2;e2++){
        const float *sp=src+(size_t)e2*M1*2*(size_t)N1*B;
        vf *dR=p->bR+(size_t)e2*st, *dI=p->bI+(size_t)e2*st;
        for(int e1=0;e1<M1;e1++){
          vf r,i; v_deint(sp,&r,&i);
          dR[e1]=r; dI[e1]=V_XOR(i,sg);
          sp+=2*(size_t)N1*B;
        } } }
    efft(N2,p->bR,p->bI,p->sR,p->sI,p->w2r,p->w2i);
    /* twiddle is a scalar per (n1,k2) now - no lane dependence, so one broadcast */
    const float *twr=p->tr+(size_t)n1*N2, *twi=p->ti+(size_t)n1*N2;
    for(int k2=0;k2<N2;k2++){
      int e=eidx(&p->eb,k2);
      vf cr=V_SET1(twr[k2]), ci=V_SET1(twi[k2]);
      vf xr=p->bR[e], xi=p->bI[e];
      size_t off=((size_t)k2*N1+n1)*B+(size_t)PF_W*g;
      V_STOREU(p->ire+off, V_FMSUB(xr,cr,V_MUL(xi,ci)));
      V_STOREU(p->iim+off, V_FMADD(xr,ci,V_MUL(xi,cr)));
    }
  }
}
static void stageB_bat(struct PBAT *p,int k2,int g,vf **RR,vf **RI){
  const int N1=p->N1,N2=p->N2,B=p->B;
  const float *sr=p->ire+((size_t)k2*N1)*B+(size_t)PF_W*g;
  const float *si=p->iim+((size_t)k2*N1)*B+(size_t)PF_W*g;
  { const int M1=p->ea.single?N1:p->a1, M2=p->ea.single?1:p->a2, st=p->ea.st;
    for(int e2=0;e2<M2;e2++){
      const float *ar=sr+(size_t)e2*M1*B, *ai=si+(size_t)e2*M1*B;
      vf *dR=p->bR+(size_t)e2*st, *dI=p->bI+(size_t)e2*st;
      for(int e1=0;e1<M1;e1++){
        dR[e1]=V_LOADU(ar); dI[e1]=V_LOADU(ai); ar+=B; ai+=B;
      } } }
  (void)N2;
  efft(N1,p->bR,p->bI,p->sR,p->sI,p->w1r,p->w1i);
  *RR=p->bR; *RI=p->bI;
}

/* full transform, batch-interleaved out[2*(k*B+b)] */
void pfbat_fft(void *vp,const float *in,float *out,int conj){
  struct PBAT *p=vp; const int N1=p->N1,N2=p->N2,B=p->B;
  const vf sg = conj?V_SIGNMASK():V_ZERO();
  for(int g=0;g<B/PF_W;g++){
    stageA_bat(p,in,g,conj);
    for(int k2=0;k2<N2;k2++){
      vf *RR,*RI; stageB_bat(p,k2,g,&RR,&RI);
      for(int k1=0;k1<N1;k1++){
        int e=eidx(&p->ea,k1);
        v_inter(out+2*(((size_t)k1*N2+k2)*B+(size_t)PF_W*g),RR[e],V_XOR(RI[e],sg));
      }
    }
  }
}
