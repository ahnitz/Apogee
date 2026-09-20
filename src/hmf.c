/* apogee: hierarchical matched filter.
 *
 * Most of a template's SNR lives in the low part of the band.  Correlate only
 * that part, on a coarse lag grid, and pay for the full correlation only where
 * the coarse result could still become a detection.
 *
 * The guarantee is one-sided: a reported peak is bit-identical to ap_mf_run's,
 * because when the gate fires this calls ap_mf_run.  Only omissions are
 * possible, at the rate the compiled-in table was calibrated for.
 *
 * Three things make the coarse pass cheap enough to be worth it:
 *
 * 1. Oversampling the coarse grid by U is NOT a zero-padded U*m-point
 *    transform.  Output parity splits it exactly:
 *        even k: m-point transform of Q
 *        odd  k: m-point transform of Q[f] * e^{i pi f/m}
 *    and that twiddle is a half-sample shift, so it folds into a second stored
 *    template at ingest and costs nothing at run time.  Two m-point transforms,
 *    not one 2m-point transform - 11% cheaper at m=512, and no new size.
 *
 * 2. The coarse series is ANALYTIC (its spectrum is on [0,1), not [-1/2,1/2)),
 *    so interpolating it with a plain sinc is wrong: that kernel relabels every
 *    bin above m/2 as a negative frequency.  It agrees exactly at the integer
 *    samples, which is why the error hides.  The right kernel is the Dirichlet
 *    one, a MODULATED sinc.  See docs/machine-notes.md.
 *
 * 3. The gate only needs |v|, and the re-modulation phase has unit magnitude,
 *    so it cancels.  demodulate -> interpolate -> re-modulate collapses into one
 *    complex tap w_k * exp(i pi (d-k)/U), applied directly to the raw series.
 */
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdio.h>
#include "apogee.h"
#include "transform.h"
#include "hmf_table.h"

#define HMF_NSUB 7            /* sub-positions per coarse interval; matches the
                                 grid the table's recovery factor was measured on */

struct ap_hmf_plan {
  size_t n, m;                /* full length; coarse band (bins kept)           */
  int U, K;                   /* coarse oversampling; interpolator taps         */
  int nd, nt;
  float snr, fd;              /* design point                                   */
  float g, graw;              /* recovery: interpolated, and raw-sample.  The
                                 gate is calibrated against g; the cheap
                                 pre-scan is bounded by graw.  Using g for the
                                 pre-scan would discard exactly the samples
                                 interpolation exists to rescue.               */
  ap_mf_plan *full;           /* refinement is the ordinary filter, unchanged   */
  /* The coarse pass IS a matched filter on an m-point plan.  Using ap_mf_plan
     rather than a hand-rolled product + transform + scan buys the fused product
     loader (the product never reaches memory), group-major spectrum storage and
     the floor-primed binned max -- all of which already exist and are tuned.
     Templates are stored in pairs: 2t is the even output half, 2t+1 the
     half-sample-shifted odd half. */
  ap_mf_plan *coarse;
  ap_plan   *cf;              /* explicit m-point plan, for the rare interpolation
                                 path that needs the series materialised        */
  float *cd;                  /* [nd][2m]   coarse data spectra, interleaved    */
  float *ct0, *ct1;           /* [nt][2m]   coarse templates: even, half-shifted*/
  float *fpow;                /* [nt]       band power fraction per template    */
  float *prod, *cev, *cod;    /* scratch: product and the two coarse halves     */
  float *taps;                /* [HMF_NSUB][K] complex interpolation bank       */
  float *tcbuf;               /* [nt] gate per template for the current run     */
  long pairs, trig;
  long npre, ninterp;   /* diagnostics: pre-gate passes, interpolations run */
  float lastgate;
};

/* Kaiser I0, series form; only ever called at plan construction. */
static double bessel_i0(double x){
  double s=1.0, t=1.0;
  for(int k=1;k<40;k++){ t*= (x*x)/(4.0*k*k); s+=t; if(t<1e-18*s) break; }
  return s;
}
static double sinc_(double x){ return fabs(x)<1e-12 ? 1.0 : sin(M_PI*x)/(M_PI*x); }

/* Build the polyphase bank.  U=1 is critically sampled: no window, because at
   critical sampling every window costs more than it buys (it attenuates exactly
   the band-edge content that sharpens the peak).  U>1 has headroom, where Kaiser
   measures best. */
static void build_taps(float *w, int K, int U){
  for(int i=0;i<HMF_NSUB;i++){
    double d=(double)(i+1)/(HMF_NSUB+1.0);
    double *b=malloc((size_t)K*sizeof(double)); double sum=0.0;
    for(int k=0;k<K;k++){
      double x=d-(double)(k-K/2+1);
      double v=sinc_(x);
      if(U>1){
        double t=((double)k-(K-1)/2.0)/((K-1)/2.0);
        double a=1.0-t*t; if(a<0) a=0;
        v*= bessel_i0(5.0*sqrt(a))/bessel_i0(5.0);
      }
      b[k]=v; sum+=v;
    }
    for(int k=0;k<K;k++){
      double x=d-(double)(k-K/2+1);
      double m=b[k]/sum, ph=M_PI*x/(double)U;
      w[2*((size_t)i*K+k)  ]=(float)(m*cos(ph));
      w[2*((size_t)i*K+k)+1]=(float)(m*sin(ph));
    }
    free(b);
  }
}

/* conj(D * conj(H)) from interleaved inputs, matching matchfilt.c's convention:
   the transform is fed conj(product) and run backward. */
static void prod_inter(const float *d,const float *h,float *o,size_t m){
  for(size_t k=0;k<m;k++){
    float x=d[2*k],y=d[2*k+1],u=h[2*k],v=h[2*k+1];
    o[2*k]  = x*u - y*v;
    o[2*k+1]= -(x*v + y*u);
  }
}

ap_hmf_plan *ap_hmf_create_ex(size_t n,int ndata,int ntmpl,float snr,float fd,
                              size_t band,int oversample,int taps){
  if(ndata<1||ntmpl<1||!ap_supported(n)) return NULL;
  if(band<1||band>=n||(band&(band-1))) return NULL;
  if(oversample!=1&&oversample!=2) return NULL;
  if(taps<2||taps>64||(taps&1)) return NULL;
  if(!ap_supported(band)) return NULL;
  ap_hmf_plan *p=calloc(1,sizeof(*p));
  if(!p) return NULL;
  p->n=n; p->m=band; p->U=oversample; p->K=taps;
  p->nd=ndata; p->nt=ntmpl; p->snr=snr; p->fd=fd;
  p->g   =hmf_recovery(n,band,oversample,taps,0);
  p->graw=hmf_recovery(n,band,oversample,taps,1);
  p->full  =ap_mf_create(n,ndata,ntmpl);
  p->coarse=ap_mf_create(band,ndata,2*ntmpl);
  p->cf    =ap_create(band);
  p->cd  =aligned_alloc(64,(size_t)ndata*2*band*sizeof(float));
  p->ct0 =aligned_alloc(64,(size_t)ntmpl*2*band*sizeof(float));
  p->ct1 =aligned_alloc(64,(size_t)ntmpl*2*band*sizeof(float));
  p->fpow=calloc((size_t)ntmpl,sizeof(float));
  p->prod=aligned_alloc(64,2*band*sizeof(float));
  p->cev =aligned_alloc(64,2*band*sizeof(float));
  p->cod =aligned_alloc(64,2*band*sizeof(float));
  p->taps=aligned_alloc(64,(size_t)2*HMF_NSUB*taps*sizeof(float));
  p->tcbuf=calloc((size_t)ntmpl,sizeof(float));
  if(!p->full||!p->coarse||!p->cf||!p->cd||!p->ct0||!p->ct1||!p->fpow||
     !p->prod||!p->cev||!p->cod||!p->taps||!p->tcbuf){ ap_hmf_destroy(p); return NULL; }
  build_taps(p->taps,taps,oversample);
  return p;
}

ap_hmf_plan *ap_hmf_create(size_t n,int ndata,int ntmpl,float snr,float fd){
  size_t band; int U,K;
  if(!hmf_choose(n,snr,fd,&band,&U,&K)) return NULL;
  return ap_hmf_create_ex(n,ndata,ntmpl,snr,fd,band,U,K);
}

void ap_hmf_destroy(ap_hmf_plan *p){
  if(!p) return;
  if(p->full) ap_mf_destroy(p->full);
  if(p->coarse) ap_mf_destroy(p->coarse);
  if(p->cf)   ap_destroy(p->cf);
  free(p->cd);free(p->ct0);free(p->ct1);free(p->fpow);
  free(p->prod);free(p->cev);free(p->cod);free(p->taps);free(p->tcbuf);
  free(p);
}

size_t ap_hmf_nbins(const ap_hmf_plan *p,size_t binsize,size_t start,size_t end){
  return p ? ap_mf_nbins(p->full,binsize,start,end) : 0;
}
void ap_hmf_stats(const ap_hmf_plan *p,long *pairs,long *triggers){
  if(!p) return;
  if(pairs) *pairs=p->pairs;
  if(triggers) *triggers=p->trig;
  if(getenv("APOGEE_HMF_DIAG"))
    fprintf(stderr,"    [diag] pairs=%ld pre-gate passes=%ld (%.1f/pair) "
            "interpolations=%ld (%.1f/pair) gate=%.3f\n",
            p->pairs,p->npre,(double)p->npre/(p->pairs?p->pairs:1),
            p->ninterp,(double)p->ninterp/(p->pairs?p->pairs:1),p->lastgate);
}
void ap_hmf_config(const ap_hmf_plan *p,size_t *band,int *oversample,int *taps){
  if(!p) return;
  if(band) *band=p->m;
  if(oversample) *oversample=p->U;
  if(taps) *taps=p->K;
}

int ap_hmf_set_data(ap_hmf_plan *p,int d,const float *spec){
  if(!p||d<0||d>=p->nd) return -1;
  if(ap_mf_set_data(p->full,d,spec)) return -1;
  memcpy(p->cd+(size_t)d*2*p->m,spec,2*p->m*sizeof(float));
  if(ap_mf_set_data(p->coarse,d,spec)) return -1;   /* only the kept band */
  return 0;
}

int ap_hmf_set_template(ap_hmf_plan *p,int t,const float *spec){
  if(!p||t<0||t>=p->nt) return -1;
  if(ap_mf_set_template(p->full,t,spec)) return -1;
  const size_t n=p->n,m=p->m;
  /* Band power fraction decides the gate: rho_c = sqrt(f)*rho_full + noise, so
     f is what sets how far the coarse value sits below the full one.  It varies
     per template, so the threshold has to as well - one global gate would be
     wrong for every template but one. */
  double tot=0,lo=0;
  for(size_t k=0;k<n;k++){
    double a=spec[2*k],b=spec[2*k+1],e=a*a+b*b;
    tot+=e; if(k<m) lo+=e;
  }
  float f = tot>0 ? (float)(lo/tot) : 0.f;
  p->fpow[t]=f;
  /* Scale by 1/sqrt(f) so the coarse output carries the same noise level as the
     full one and the two thresholds are directly comparable. */
  double s = lo>0 ? 1.0/sqrt(lo/tot) : 0.0;
  float *a0=p->ct0+(size_t)t*2*m, *a1=p->ct1+(size_t)t*2*m;
  for(size_t k=0;k<m;k++){
    double re=spec[2*k]*s, im=spec[2*k+1]*s;
    a0[2*k]=(float)re; a0[2*k+1]=(float)im;
    /* half-sample shift: H[f] * e^{+i pi f/m} gives the odd output samples */
    double c=cos(M_PI*(double)k/(double)m), sn=sin(M_PI*(double)k/(double)m);
    a1[2*k]  =(float)(re*c-im*sn);
    a1[2*k+1]=(float)(re*sn+im*c);
  }
  if(ap_mf_set_template(p->coarse,2*t,  a0)) return -1;
  if(ap_mf_set_template(p->coarse,2*t+1,a1)) return -1;
  return 0;
}

/* |interpolated value| at sub-position i around coarse sample j.  The series is
   circular - apogee's correlation is - so wrapped taps are exact, not an edge
   approximation. */
static float interp_abs(const float *ev,const float *od,size_t m,int U,
                        const float *w,int K,int i,long j){
  const long G=(long)m*U;
  float sr=0.f,si=0.f;
  for(int k=0;k<K;k++){
    long jj=j+k-K/2+1; jj%=G; if(jj<0) jj+=G;
    const float *z = (U==1) ? ev+2*jj
                            : ((jj&1) ? od+((jj>>1)*2) : ev+((jj>>1)*2));
    float zr=z[0],zi=z[1];
    float wr=w[2*((size_t)i*K+k)],wi=w[2*((size_t)i*K+k)+1];
    sr += wr*zr - wi*zi;
    si += wr*zi + wi*zr;
  }
  return sqrtf(sr*sr+si*si);
}

int ap_hmf_run(ap_hmf_plan *p,int d0,int nd,int t0,int nt,
               size_t binsize,float threshold,
               ap_peak *peaks,int *counts,size_t start,size_t end){
  if(!p||nd<1||nt<1||!binsize) return 0;
  if(d0<0||d0+nd>p->nd||t0<0||t0+nt>p->nt) return -1;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  const size_t n=p->n,m=p->m; const int U=p->U,K=p->K;
  const size_t nb=ap_mf_nbins(p->full,binsize,start,end);
  (void)U;
  /* coarse index range covering the window; the grid step is n/G lags */
  /* Recalibrate the gate for the weakest signal that can actually be REPORTED,
     which is max(snr, threshold).  Two wrong ways to do this:
       - gate at max(tc, threshold): raises the gate above what snr calibrated,
         so it dismisses at a rate the design never bounded.
       - gate at tc alone when threshold > snr: correct but wasteful, since
         signals between snr and threshold are discarded by the full filter
         anyway, and calibrating for them only opens the gate needlessly.
     Both the threshold and snr are in units where the noise has unit-variance
     components, which is the caller's pre-normalisation contract. */
  float *tcs=p->tcbuf;
  {
    float T = threshold>p->snr ? threshold : p->snr;
    for(int t=0;t<nt;t++)
      tcs[t]=hmf_threshold(p->fpow[t0+t]*p->g*p->g,T,p->fd);
  }
  /* Coarse lag window.  Even sample j maps to full lag j*R, odd to j*R + R/2,
     so one range covers both to within half a coarse step; widening by one step
     keeps it conservative.  A single bin spanning the range makes the reported
     peak the maximum. */
  const size_t R=n/m;
  size_t cstart = start/R;
  size_t cend   = (end+R-1)/R; if(cend>m) cend=m;
  if(cstart>0) cstart--;
  const size_t cspan = cend>cstart ? cend-cstart : 1;
  int total=0;
  for(int d=0;d<nd;d++){
    const float *Dc=p->cd+(size_t)(d0+d)*2*m;
    for(int t=0;t<nt;t++){
      const size_t row=(size_t)d*nt+t;
      p->pairs++;
      const float gate = tcs[t]; p->lastgate=gate;
      const float raw_gate = gate*p->graw*0.999f;
      /* Fused coarse pass: product, transform and maximum in one kernel, with
       * the product never reaching memory.  One bin spanning the whole coarse
       * window means the reported peak IS the maximum, so the separate scan
       * that used to walk the materialised series disappears entirely.
       * Threshold at raw_gate: below it, interpolation cannot reach the gate,
       * so ap_mf_run returns index<0 and there is nothing more to do. */
      ap_peak ce,co; int cc=0;
      ce.index=co.index=-1; ce.magnitude=co.magnitude=0.f;
      if(ap_mf_run(p->coarse,d0+d,1,2*(t0+t),1,cspan,raw_gate,&ce,&cc,cstart,cend)<0)
        return -1;
      if(U>1 && ap_mf_run(p->coarse,d0+d,1,2*(t0+t)+1,1,cspan,raw_gate,&co,&cc,
                          cstart,cend)<0) return -1;
      float bestmag = ce.magnitude>co.magnitude ? ce.magnitude : co.magnitude;
      int fire = bestmag>=gate;
      if(!fire && bestmag>=raw_gate){
        /* Rare: the raw maximum sits in [graw*gate, gate), the only window where
           interpolation can change the answer.  Only here is the series worth
           materialising, and only around the argmax -- which is exactly what the
           table's recovery factor was measured on. */
        p->npre++;
        long bestj = (ce.magnitude>=co.magnitude) ? 2*(long)ce.index
                                                  : 2*(long)co.index+1;
        if(U==1) bestj=(long)ce.index;
        prod_inter(Dc,p->ct0+(size_t)(t0+t)*2*m,p->prod,m);
        ap_fft(p->cf,p->prod,p->cev,AP_BACKWARD);
        if(U>1){
          prod_inter(Dc,p->ct1+(size_t)(t0+t)*2*m,p->prod,m);
          ap_fft(p->cf,p->prod,p->cod,AP_BACKWARD);
        }
        for(int i=0;i<HMF_NSUB && !fire;i++){
          p->ninterp+=2;
          if(interp_abs(p->cev,p->cod,m,U,p->taps,K,i,bestj-1) >= gate) fire=1;
          else if(interp_abs(p->cev,p->cod,m,U,p->taps,K,i,bestj) >= gate) fire=1;
        }
      }
      if(fire){
        p->trig++;
        int c=0;
        int r=ap_mf_run(p->full,d0+d,1,t0+t,1,binsize,threshold,
                        peaks+row*nb,&c,start,end);
        if(r<0) return -1;
        if(counts) counts[row]=c;
        total+=c;
      }else{
        for(size_t b=0;b<nb;b++){
          peaks[row*nb+b].index=-1;
          peaks[row*nb+b].re=peaks[row*nb+b].im=peaks[row*nb+b].magnitude=0.f;
        }
        if(counts) counts[row]=0;
      }
    }
  }
  return total;
}
