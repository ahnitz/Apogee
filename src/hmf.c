/* matchedfilter: hierarchical matched filter.
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
#include "ticks.h"
#include "alloc.h"
#include "matchedfilter.h"
#include "transform.h"
#include "hmf_table.h"

#define HMF_NSUB 7            /* sub-positions per coarse interval; matches the
                                 grid the table's recovery factor was measured on */

struct ap_hmf_plan {
  size_t n, m;                /* full length; coarse band (bins kept)           */
  int U, K;                   /* coarse oversampling; interpolator taps         */
  int nd, nt;
  float snr, fd;              /* design point                                   */
  ap_mf_plan *full;           /* refinement is the ordinary filter, unchanged   */
  /* The coarse pass IS a matched filter on an m-point plan.  Using ap_mf_plan
     rather than a hand-rolled product + transform + scan buys the fused product
     loader (the product never reaches memory), group-major spectrum storage and
     the floor-primed binned max -- all of which already exist and are tuned.
     Even halves occupy [0, nt) and odd halves [nt, 2nt), NOT interleaved as
     2t/2t+1.  The even half is the only one touched on the ~78% of pairs where
     the early-out fires, so keeping the evens contiguous walks 16 KiB of
     templates instead of striding through 32 KiB. */
  ap_mf_plan *coarse;
  ap_plan   *full_fft;        /* n-point plan for the forward transform of a block */
  float     *fwd,*spec;       /* [2n] block staging and its spectrum            */
  ap_plan   *cf;              /* explicit m-point plan, for the rare interpolation
                                 path that needs the series materialised        */
  float *cd;                  /* [nd][2m]   coarse data spectra, interleaved    */
  const float **dspec;        /* [nd]       caller's full spectra, ingested lazily */
  char *dready;               /* [nd]       1 once ingested into the full plan  */
  float *ct0, *ct1;           /* [nt][2m]   coarse templates: even, half-shifted*/
  float *fpow;                /* [nt]       band power fraction per template    */
  /* Reference SNR distribution, or ref_on=0 to measure per template.  The
     output distribution is a property of the signal rather than of any one
     template, so one reference serves a whole bank -- and skips the
     per-template ingest measurement. */
  int    ref_on;
  float  even_margin, gate_margin;
  float  ref_f, ref_g, ref_graw, ref_graw1;
  float *tg,*tgraw,*tgraw1;   /* [nt]       per-template recovery factors       */
  float *shift;               /* [2m]       scratch for the measurement         */
  float *shift2;              /* [4m]       weighted template copies            */
  float *prod, *cev, *cod;    /* scratch: product and the two coarse halves     */
  float *taps;                /* [HMF_NSUB][K] complex interpolation bank       */
  float *tcbuf,*rawbuf,*evenbuf; /* [nt] per-template gates, derived once a run */
  ap_peak *cebuf;             /* [nt] even coarse maxima for one data segment */
  int *firebuf;               /* [nt] which templates fired, for one segment */
  long pairs, trig;
  /* Phase counters in cycles.  rdtsc, not clock_gettime: the latter costs
     ~25 ns and these phases are ~200 ns, so it would measure itself. */
  unsigned long long c_even,c_odd,c_ref,c_fill; int prof;
  FILE *dump;          /* MF_HMF_DUMP: per-pair (even, combined, gate) */
  long npre, ninterp, nskip;   /* diagnostics: pre-gate passes, interpolations run */
  float lastgate;
  float fs_snr;        /* explicit first-stage SNR; <=0 means derive it */
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
   the transform is fed conj(product) and run backward.  H is expected ALREADY
   CONJUGATED, as ap_mf_set_template stores it. */
static void prod_inter(const float *d,const float *h,float *o,size_t m){
  for(size_t k=0;k<m;k++){
    float x=d[2*k],y=d[2*k+1],u=h[2*k],v=h[2*k+1];
    o[2*k]  = x*u - y*v;
    o[2*k+1]= -(x*v + y*u);
  }
}

/* Same product, but taking H unconjugated.  measure_recovery holds the coarse
   templates in the form ap_mf_set_template was handed, i.e. before that call
   conjugated them, so it must do the conjugation itself.  Passing them to
   prod_inter instead silently measures conj(D*H) -- the wrong series, giving
   wrong recovery factors and a gate far below where it belongs. */
static void prod_inter_nc(const float *d,const float *h,float *o,size_t m){
  for(size_t k=0;k<m;k++){
    float x=d[2*k],y=d[2*k+1],u=h[2*k],v=h[2*k+1];
    o[2*k]  = x*u + y*v;
    o[2*k+1]= x*v - y*u;
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
  p->full  =ap_mf_create(n,ndata,ntmpl);
  p->coarse=ap_mf_create(band,ndata,2*ntmpl);
  p->cf      =ap_create(band);
  p->full_fft=ap_create(n);
  p->fwd =ap_alloc64(2*n*sizeof(float));
  p->spec=ap_alloc64(2*n*sizeof(float));
  p->cd  =ap_alloc64((size_t)ndata*2*band*sizeof(float));
  p->dspec=calloc((size_t)ndata,sizeof(*p->dspec));
  p->dready=calloc((size_t)ndata,1);
  p->ct0 =ap_alloc64((size_t)ntmpl*2*band*sizeof(float));
  p->ct1 =ap_alloc64((size_t)ntmpl*2*band*sizeof(float));
  p->fpow=calloc((size_t)ntmpl,sizeof(float));
  p->tg=calloc((size_t)ntmpl,sizeof(float));
  p->tgraw=calloc((size_t)ntmpl,sizeof(float));
  p->tgraw1=calloc((size_t)ntmpl,sizeof(float));
  p->shift=ap_alloc64(2*band*sizeof(float));
  p->shift2=ap_alloc64(4*band*sizeof(float));
  p->prod=ap_alloc64(2*band*sizeof(float));
  p->cev =ap_alloc64(2*band*sizeof(float));
  p->cod =ap_alloc64(2*band*sizeof(float));
  p->taps=ap_alloc64((size_t)2*HMF_NSUB*taps*sizeof(float));
  p->tcbuf=calloc((size_t)ntmpl,sizeof(float));
  p->rawbuf=calloc((size_t)ntmpl,sizeof(float));
  p->evenbuf=calloc((size_t)ntmpl,sizeof(float));
  p->cebuf=calloc((size_t)ntmpl,sizeof(ap_peak));
  p->firebuf=calloc((size_t)ntmpl,sizeof(int));
  if(!p->full||!p->coarse||!p->cf||!p->full_fft||!p->fwd||!p->spec||!p->cd||!p->dspec||!p->dready||!p->ct0||!p->ct1||!p->fpow||!p->tg||!p->tgraw||!p->tgraw1||!p->shift||!p->shift2||
     !p->prod||!p->cev||!p->cod||!p->taps||!p->tcbuf||!p->rawbuf||!p->evenbuf||!p->cebuf||!p->firebuf){ ap_hmf_destroy(p); return NULL; }
  build_taps(p->taps,taps,oversample);
  /* Safety factor on the even gate, over and above the measured graw1.
     The realisation model is a power-law reference filtered by a matched
     template; the ratio filter's product is shaped differently, and on 12
     captured pycbc segments the real even/combined ratio reached 0.809 where
     the model says 0.897.  Swept against those captures over 811 triggers:
     0.92 and below lose nothing, 0.95 loses one (1.2e-3, already past the
     1e-3 budget) and 1.00 loses sixteen. */
  /* Scale on the gate the design table derives.  1.0 is that table's own
     answer, and on 12 captured pycbc segments it misses 31 of 842 real
     triggers -- 3.7%, and 13% for triggers within 0.5% of the threshold,
     against a 1e-3 budget.  0.94 recovers all of them, at 2.51x against the
     flat filter where 1.0 gives 3.32x.  The table's recovery factors are
     measured from a mean spectrum and are not a bound on a realisation; see
     docs/hierarchical.md.  Until that is fixed this is the honest control. */
  p->gate_margin=1.0f;
  { const char *e=getenv("MF_GATE_MARGIN"); if(e) p->gate_margin=(float)atof(e); }
  p->even_margin=0.92f;
  { const char *e=getenv("MF_EVEN_MARGIN"); if(e) p->even_margin=(float)atof(e); }
  p->prof = getenv("MF_HMF_PROF") ? 1 : 0;
  { const char *e=getenv("MF_HMF_DUMP"); p->dump = e ? fopen(e,"wb") : NULL; }
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
  if(p->full_fft) ap_destroy(p->full_fft);
  free(p->fwd);free(p->spec);
  free(p->dspec);free(p->dready);free(p->cd);free(p->ct0);free(p->ct1);free(p->fpow);
  if(p->dump) fclose(p->dump);
  free(p->tg);free(p->tgraw);free(p->tgraw1);free(p->shift);free(p->shift2);
  free(p->prod);free(p->cev);free(p->cod);free(p->taps);free(p->tcbuf);free(p->rawbuf);free(p->evenbuf);free(p->cebuf);free(p->firebuf);
  free(p);
}

size_t ap_hmf_nbins(const ap_hmf_plan *p,size_t binsize,size_t start,size_t end){
  return p ? ap_mf_nbins(p->full,binsize,start,end) : 0;
}
void ap_hmf_stats(const ap_hmf_plan *p,long *pairs,long *triggers){
  if(!p) return;
  if(pairs) *pairs=p->pairs;
  if(triggers) *triggers=p->trig;
  if(p->prof && p->pairs){
    /* Cycles per pair.  The even pass is batched per data segment, so its
       counter is the segment cost divided across that segment's pairs. */
    double tot=(double)(p->c_even+p->c_odd+p->c_ref+p->c_fill);
    fprintf(stderr,"    [prof] cycles/pair: even=%.0f (%.0f%%) odd=%.0f (%.0f%%) "
            "refine=%.0f (%.0f%%) fill=%.0f (%.0f%%)\n",
            (double)p->c_even/p->pairs,100*p->c_even/tot,
            (double)p->c_odd /p->pairs,100*p->c_odd /tot,
            (double)p->c_ref /p->pairs,100*p->c_ref /tot,
            (double)p->c_fill/p->pairs,100*p->c_fill/tot);
  }
  if(getenv("MF_HMF_DIAG"))
    fprintf(stderr,"    [diag] pairs=%ld pre-gate passes=%ld (%.1f/pair) "
            "interpolations=%ld (%.1f/pair) odd-skipped=%.1f%% gate=%.3f\n",
            p->pairs,p->npre,(double)p->npre/(p->pairs?p->pairs:1),
            p->ninterp,(double)p->ninterp/(p->pairs?p->pairs:1),
            100.0*p->nskip/(p->pairs?p->pairs:1),p->lastgate);
}
void ap_hmf_config(const ap_hmf_plan *p,size_t *band,int *oversample,int *taps){
  if(!p) return;
  if(band) *band=p->m;
  if(oversample) *oversample=p->U;
  if(taps) *taps=p->K;
}

static void measure_recovery(ap_hmf_plan *p,int t,const float *a0,const float *a1,
                             float *gout,float *grawout,float *graw1out);

int ap_hmf_set_first_stage(ap_hmf_plan *p,float snr){
  if(!p) return -1;
  p->fs_snr = snr > 0.0f ? snr : 0.0f;   /* <=0 restores the derived level */
  return 0;
}

int ap_hmf_set_reference(ap_hmf_plan *p,const float *power){
  if(!p) return -1;
  if(!power){ p->ref_on=0; return 0; }
  const size_t n=p->n,m=p->m;
  double tot=0,lo=0;
  for(size_t k=0;k<n;k++){ double e=power[k]>0?power[k]:0; tot+=e; if(k<m) lo+=e; }
  if(tot<=0) return -1;
  p->ref_f=(float)(lo/tot);
  /* Recovery depends only on |H|^2, so a zero-phase template with magnitude
     sqrt(power) has exactly the right autocorrelation shape. */
  float *a0=p->shift2, *a1=p->shift2+2*m;
  double s = lo>0 ? 1.0/sqrt(lo/tot) : 0.0;
  for(size_t k=0;k<m;k++){
    double re=sqrt(power[k]>0?power[k]:0)*s, im=0.0;
    a0[2*k]=(float)re; a0[2*k+1]=(float)im;
    double c=cos(M_PI*(double)k/(double)m), sn=sin(M_PI*(double)k/(double)m);
    a1[2*k]  =(float)(re*c-im*sn);
    a1[2*k+1]=(float)(re*sn+im*c);
  }
  measure_recovery(p,0,a0,a1,&p->ref_g,&p->ref_graw,&p->ref_graw1);

  /* graw1 from the average spectrum is not a bound on a realisation.
   *
   * The early-out skips the odd transform when the even samples alone cannot
   * reach the gate, which needs a bound on even_max/combined_max.  Derived
   * from the reference's autocorrelation that is a MEAN shape: an individual
   * noise peak can be sharper, the even grid then loses more than the mean
   * predicts, and the peak is dismissed.  Measured in a real search this cost
   * 2.9% of triggers against a 0.1% budget -- and it only bites where the grid
   * is fine (R small), which is why a coarser configuration never showed it.
   *
   * So measure the ratio over realisations and take a low quantile.  This runs
   * once per reference, not per template.
   */
  {
    /* Sample size and quantile.  The original took the second smallest of 128,
       which is one unlucky draw away from anything: on a real captured search
       it returned 0.74 where no pair in 27000 went below 0.81, and the even
       gate then opened on 70% of pairs.  A quantile needs enough samples to be
       a quantile. */
    const int K=128;
    /* Noise levels to sweep.  The pairs this gate decides are the marginal
       ones, where the combined maximum is barely at the gate and may be a
       noise peak rather than the signal.  Simulating at one high SNR only
       ever reproduces the noiseless scallop, which is what the even gate is
       NOT allowed to assume. */
    static const double nzlev[4]={0.35,0.8,1.6,3.2};
    float *rat=malloc((size_t)K*sizeof(float));
    unsigned long long rs=0x9E3779B97F4A7C15ULL;
    for(int r=0;r<K;r++){
      for(size_t k=0;k<m;k++){
        /* signal at a random lag plus noise, both shaped by the reference */
        rs^=rs<<13; rs^=rs>>7; rs^=rs<<17;
        double u1=((rs>>11)*(1.0/9007199254740992.0))+1e-12;
        rs^=rs<<13; rs^=rs>>7; rs^=rs<<17;
        double u2=(rs>>11)*(1.0/9007199254740992.0);
        double g1=sqrt(-2*log(u1))*cos(2*M_PI*u2);
        double g2=sqrt(-2*log(u1))*sin(2*M_PI*u2);
        /* The product spectrum, not the data spectrum.  D ~ amp*(signal +
           noise) and T ~ amp, so D*conj(T) carries amp^2 = power[k].  Shaping
           these realisations by amp instead made the spectrum flatter than the
           real one, which narrows the correlation peak and deepens the scallop
           between even samples: it returned 0.74 where the same reference's
           noiseless scallop is 0.90 and no pair in a 27000-pair captured
           search went below 0.81. */
        double amp=power[k]>0?power[k]:0;
        /* Fractional lag: coarse index j is full lag j*R, so an integer index
           only ever lands on the even grid -- exactly the blind spot being
           measured.  Step in quarters so odd and inter-sample lags are covered. */
        double L=0.25*(double)(r%32);
        double ph=2.0*M_PI*(double)k*L/(double)m;
        const double nz=nzlev[(r/32)&3];
        p->prod[2*k]  =(float)(amp*(cos(ph)+nz*g1));
        p->prod[2*k+1]=(float)(amp*(sin(ph)+nz*g2));
      }
      ap_fft(p->cf,p->prod,p->cev,AP_BACKWARD);
      for(size_t k=0;k<m;k++){
        double c=cos(M_PI*(double)k/(double)m), sn=sin(M_PI*(double)k/(double)m);
        float xr=p->prod[2*k], xi=p->prod[2*k+1];
        p->shift[2*k]  =(float)(xr*c-xi*sn);
        p->shift[2*k+1]=(float)(xr*sn+xi*c);
      }
      ap_fft(p->cf,p->shift,p->cod,AP_BACKWARD);
      float be=0.f,bo=0.f;
      for(size_t j=0;j<m;j++){
        float e=p->cev[2*j]*p->cev[2*j]+p->cev[2*j+1]*p->cev[2*j+1];
        float o=p->cod[2*j]*p->cod[2*j]+p->cod[2*j+1]*p->cod[2*j+1];
        if(e>be) be=e;
        if(o>bo) bo=o;
      }
      float comb = be>bo?be:bo;
      rat[r] = comb>0.f ? sqrtf(be/comb) : 1.f;
    }
    /* low quantile: second smallest of 128 is about the 1% point */
    for(int i=0;i<3;i++)
      for(int j=i+1;j<K;j++)
        if(rat[j]<rat[i]){ float t=rat[i]; rat[i]=rat[j]; rat[j]=t; }
    float q=rat[1];
    if(getenv("MF_HMF_DIAG"))
      fprintf(stderr,"    [diag] graw1: scallop %.4f  realisations %.4f -> %.4f\n",
              p->ref_graw1, q, q<p->ref_graw1?q:p->ref_graw1);
    if(q<p->ref_graw1) p->ref_graw1=q;
    free(rat);
  }
  p->ref_on=1;
  return 0;
}

int ap_hmf_set_data(ap_hmf_plan *p,int d,const float *spec){
  if(!p||d<0||d>=p->nd) return -1;
  /* The FULL plan's ingest is a group-major transpose of n complex, and the
     gate discards it on the overwhelming majority of pairs -- 99.9% at a 0.1%
     trigger rate.  Keep the caller's pointer instead and ingest lazily, the
     first time a pair on this data segment actually reaches refinement.  The
     spectrum must stay valid until run() returns, which is already the
     contract: set_data then run. */
  p->dspec[d]=spec;
  p->dready[d]=0;
  memcpy(p->cd+(size_t)d*2*p->m,spec,2*p->m*sizeof(float));
  if(ap_mf_set_data(p->coarse,d,spec)) return -1;   /* only the kept band */
  return 0;
}

static float interp_abs(const float *ev,const float *od,size_t m,int U,
                        const float *w,int K,int i,long j);

/* Measure this template's own recovery factors instead of inheriting the
 * table's.
 *
 * The table's figures were measured on the design template (85% of its power in
 * the lowest n/8 bins).  Recovery depends on the spectral shape *inside* the
 * kept band -- a flatter template has a sharper correlation peak and recovers
 * less -- so a caller whose templates differ would have gates calibrated for a
 * peak shape they do not have, and would lose detections with nothing to show
 * for it.  Preprocessing is free here (T >> D), so measure it exactly.
 *
 * The continuous peak needs no fine transform: for a template matched against
 * itself it is exactly sum |Hn[f]|^2 over the kept band.  So the whole
 * measurement is nsub sub-offsets x two m-point transforms, per template.
 */
static void measure_recovery(ap_hmf_plan *p,int t,const float *a0,const float *a1,
                             float *gout,float *grawout,float *graw1out){
  const size_t m=p->m,n=p->n; const int U=p->U,K=p->K;
  const size_t R=n/m;
  /* Offsets must span the coarsest grid being measured, which is the EVEN
     grid, spacing R -- not the combined U=2 grid, spacing R/U.
     graw1 describes what the even samples alone recover, so offsets that only
     span R/U never test a peak sitting between two even samples.  At R=2, U=2
     that left exactly one offset, the aligned one, and graw1 came back 1.0 when
     the true figure was 0.958: the even gate was then ~4% too high and every
     peak on an odd lag was silently dismissed.  Spanning R covers both grids.
     Stride so the sampled set spans the interval even when R is large. */
  size_t nstep=R; if(!nstep) nstep=1;
  size_t stride=nstep/16; if(!stride) stride=1;
  double peak=0;
  for(size_t k=0;k<m;k++) peak+=(double)a0[2*k]*a0[2*k]+(double)a0[2*k+1]*a0[2*k+1];
  if(peak<=0){ *gout=1.f; *grawout=0.7f; *graw1out=0.7f; return; }
  const float pk=(float)peak;
  float gr=9.f,g1=9.f,gi=9.f;
  float *Ds=p->shift;
  for(size_t s=0;s<nstep;s+=stride){
    const double off=-2.0*M_PI*(double)s/(double)n;   /* s is in lags */
    for(size_t k=0;k<m;k++){
      double c=cos(off*(double)k), sn=sin(off*(double)k);
      Ds[2*k]  =(float)(a0[2*k]*c-a0[2*k+1]*sn);
      Ds[2*k+1]=(float)(a0[2*k]*sn+a0[2*k+1]*c);
    }
    prod_inter_nc(Ds,a0,p->prod,m); ap_fft(p->cf,p->prod,p->cev,AP_BACKWARD);
    if(U>1){ prod_inter_nc(Ds,a1,p->prod,m); ap_fft(p->cf,p->prod,p->cod,AP_BACKWARD); }
    const size_t G=m*(size_t)U;
    float be=0.f,ball=0.f; long bj=0;
    for(size_t j=0;j<G;j++){
      const float *z=(U==1)?p->cev+2*j:((j&1)?p->cod+((j>>1)*2):p->cev+((j>>1)*2));
      float v=sqrtf(z[0]*z[0]+z[1]*z[1]);
      if(v>ball){ ball=v; bj=(long)j; }
      if(U==1||!(j&1)){ if(v>be) be=v; }
    }
    float bi=ball;
    for(int i=0;i<HMF_NSUB;i++){
      float u1=interp_abs(p->cev,p->cod,m,U,p->taps,K,i,bj-1);
      float u2=interp_abs(p->cev,p->cod,m,U,p->taps,K,i,bj);
      if(u1>bi) bi=u1;
      if(u2>bi) bi=u2;
    }
    if(ball/pk<gr) gr=ball/pk;
    if(be  /pk<g1) g1=be/pk;
    if(bi  /pk<gi) gi=bi/pk;
  }
  /* Clamp to <=1: the interpolator can overshoot slightly, and a recovery above
     1 would raise the gate above what the statistics justify. */
  *gout     = gi>1.f?1.f:gi;
  *grawout  = gr>1.f?1.f:gr;
  *graw1out = g1>1.f?1.f:g1;
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
  if(p->ref_on) f = p->ref_f;      /* the signal's fraction, not the filter's */
  p->fpow[t]=f;
  /* Scale by 1/sqrt(f) so the coarse output carries the same noise level as the
     full one and the two thresholds are directly comparable.  f here must be
     the SIGNAL's band fraction: the coarse noise variance is
     s^2 * sum_{k<m}|H|^2 W and the full one sum_k |H|^2 W, so s^2 = 1/f with
     the same W the reference describes.  Using the template's own fraction
     would mis-scale the coarse output and shift the gate off calibration. */
  double s = f>0.f ? 1.0/sqrt((double)f) : 0.0;
  float *a0=p->ct0+(size_t)t*2*m, *a1=p->ct1+(size_t)t*2*m;
  for(size_t k=0;k<m;k++){
    double re=spec[2*k]*s, im=spec[2*k+1]*s;
    a0[2*k]=(float)re; a0[2*k+1]=(float)im;
    /* half-sample shift: H[f] * e^{+i pi f/m} gives the odd output samples */
    double c=cos(M_PI*(double)k/(double)m), sn=sin(M_PI*(double)k/(double)m);
    a1[2*k]  =(float)(re*c-im*sn);
    a1[2*k+1]=(float)(re*sn+im*c);
  }
  if(ap_mf_set_template(p->coarse,t,        a0)) return -1;
  if(ap_mf_set_template(p->coarse,p->nt+t,  a1)) return -1;
  /* Recovery depends on the shape of the correlation peak, which is set by the
     OUTPUT spectrum |H|^2 w -- not by the template alone.  Measure it on a
     weighted copy; the stored template stays unweighted, because at run time
     the data supplies w itself. */
  if(p->ref_on){
    p->tg[t]=p->ref_g; p->tgraw[t]=p->ref_graw; p->tgraw1[t]=p->ref_graw1;
  } else {
    measure_recovery(p,t,a0,a1,&p->tg[t],&p->tgraw[t],&p->tgraw1[t]);
  }
  return 0;
}

/* |interpolated value| at sub-position i around coarse sample j.  The series is
   circular - matchedfilter's correlation is - so wrapped taps are exact, not an edge
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

int ap_hmf_run_series(ap_hmf_plan *p,
                      const float *series,size_t nseries,
                      const size_t *start,const size_t *win_start,
                      const size_t *win_end,int nblocks,
                      int t0,int nt,size_t binsize,float threshold,
                      ap_peak *peaks,int *counts){
  if(!p||nblocks<1||nt<1||!binsize) return 0;
  if(t0<0||t0+nt>p->nt) return -1;
  const size_t n=p->n;
  int total=0;
  for(int b=0;b<nblocks;b++){
    /* Forward transform this block.  Short tails are zero-padded, which is what
       the caller's layout already assumes for the final block of a segment. */
    const size_t s0=start[b];
    size_t have = s0<nseries ? nseries-s0 : 0;
    if(have>n) have=n;
    if(have) memcpy(p->fwd,series+2*s0,2*have*sizeof(float));
    if(have<n) memset(p->fwd+2*have,0,2*(n-have)*sizeof(float));
    ap_fft(p->full_fft,p->fwd,p->spec,AP_FORWARD);
    /* pycbc's inverse is unnormalised and so is matchedfilter's, so the caller's
       convention of pre-dividing the block spectrum by n is preserved here. */
    { const float inv=1.0f/(float)n;
      for(size_t k=0;k<2*n;k++) p->spec[k]*=inv; }
    if(ap_hmf_set_data(p,0,p->spec)) return -1;
    size_t nb=ap_mf_nbins(p->full,binsize,win_start[b],win_end[b]);
    int r=ap_hmf_run(p,0,1,t0,nt,binsize,threshold,
                     peaks+(size_t)b*nt*nb,counts?counts+(size_t)b*nt:NULL,
                     win_start[b],win_end[b]);
    if(r<0) return -1;
    total+=r;
  }
  return total;
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
  /* All three gates depend only on the template, so derive them once per run
     rather than per pair.  With D data segments and T templates the pair loop
     runs D*T times and this runs T times: the whole point of the D x T shape is
     that anything one-sided belongs outside the product. */
  float *tcs=p->tcbuf, *rawg=p->rawbuf, *eveng=p->evenbuf;
  {
    /* The SNR the first stage is calibrated against.  By default the search
       threshold (or the plan's, whichever is higher), but a caller may set it
       directly: the first stage then tests at that SNR while final triggers
       are still cut at `threshold`.  This only moves the level -- band,
       oversample and taps are chosen when the plan is created and are not
       disturbed, so it is a threshold and not a different configuration. */
    float T = p->fs_snr > 0.0f ? p->fs_snr
                               : (threshold>p->snr ? threshold : p->snr);
    for(int t=0;t<nt;t++){
      float gt=p->tg[t0+t];
      tcs[t]=hmf_threshold(p->fpow[t0+t]*gt*gt,T,p->fd)*p->gate_margin;
      rawg[t] =tcs[t]*p->tgraw [t0+t]*0.999f;
      eveng[t]=tcs[t]*p->tgraw1[t0+t]*p->even_margin;
    }
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
  /* Even coarse pass for ALL templates of a data segment in one call.  The
     data spectrum is read once and stays resident across the whole template
     sweep, and consecutive transforms are no longer separated by the gate
     branch, so they can overlap.  One threshold has to serve every template, so
     use the lowest: a template whose own gate is higher is filtered below, and
     a lower threshold only ever reports MORE peaks. */
  float minev=eveng[0];
  for(int t=1;t<nt;t++) if(eveng[t]<minev) minev=eveng[t];
  int total=0;
  for(int d=0;d<nd;d++){
    const float *Dc=p->cd+(size_t)(d0+d)*2*m;
    unsigned long long _eb = p->prof ? ap_ticks() : 0;
    if(ap_mf_run(p->coarse,d0+d,1,t0,nt,cspan,minev,p->cebuf,NULL,
                 cstart,cend)<0) return -1;
    if(p->prof) p->c_even += ap_ticks()-_eb;   /* batched: charged to the segment */
    int nfire=0;
    for(int t=0;t<nt;t++){
      const size_t row=(size_t)d*nt+t;
      p->pairs++;
      const float gate = tcs[t]; p->lastgate=gate;
      const float raw_gate  = rawg[t];
      int fire=0;
      /* Fused coarse pass: product, transform and maximum in one kernel, with
       * the product never reaching memory.  One bin spanning the whole coarse
       * window means the reported peak IS the maximum, so the separate scan
       * that used to walk the materialised series disappears entirely.
       * Threshold at raw_gate: below it, interpolation cannot reach the gate,
       * so ap_mf_run returns index<0 and there is nothing more to do. */
      ap_peak ce,co; int cc=0;
      co.index=-1; co.magnitude=0.f;
      /* Even half first, thresholded at graw1*gate rather than graw*gate.  The
       * even samples alone are the U=1 series, so if their maximum falls below
       * graw1*gate the true continuous peak cannot reach the gate no matter
       * what the odd samples hold - and the odd transform, half the coarse
       * cost, is skipped outright.  On noise that is the overwhelming majority
       * of pairs.  It must be graw1 and not graw: graw describes the combined
       * U=2 grid, which recovers more, so using it here would cut off peaks the
       * odd half would have found. */
      const float even_gate = eveng[t];
      unsigned long long _t0 = p->prof ? ap_ticks() : 0;
      ce = p->cebuf[t];
      if(ce.index>=0 && ce.magnitude<even_gate) ce.index=-1;   /* per-template gate */
      if(ce.index<0){
        if(getenv("MF_HMF_TRACE") && p->pairs<6)
          fprintf(stderr,"    [trace] pair=%ld gate=%.3f even_gate=%.3f "
                  "even max BELOW even_gate\n",p->pairs,gate,even_gate);
                                            /* cannot reach the gate: done */
        p->nskip++;
        goto verdict;
      }
      if(U>1 && ap_mf_run(p->coarse,d0+d,1,p->nt+t0+t,1,cspan,raw_gate,&co,&cc,
                          cstart,cend)<0) return -1;
      if(p->prof){ unsigned long long t1=ap_ticks(); p->c_odd+=t1-_t0; _t0=t1; }
      float bestmag = ce.magnitude>co.magnitude ? ce.magnitude : co.magnitude;
      if(p->dump){ float rec[3]={ce.magnitude,bestmag,gate};
                   fwrite(rec,sizeof rec,1,p->dump); }
      if(getenv("MF_HMF_TRACE") && p->pairs<6)
        fprintf(stderr,"    [trace] pair=%ld gate=%.3f even_gate=%.3f "
                "coarse max=%.3f (even %.3f odd %.3f)\n",
                p->pairs,gate,even_gate,bestmag,ce.magnitude,co.magnitude);
      fire = bestmag>=gate;
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
      verdict:
      if(fire){
        p->trig++;
        p->firebuf[nfire++]=t;   /* reconstructed together, after this loop */
      }else{
        unsigned long long f0 = p->prof ? ap_ticks() : 0;
        for(size_t b=0;b<nb;b++){
          peaks[row*nb+b].index=-1;
          peaks[row*nb+b].re=peaks[row*nb+b].im=peaks[row*nb+b].magnitude=0.f;
        }
        if(counts) counts[row]=0;
        if(p->prof) p->c_fill += ap_ticks()-f0;
      }
    }
    /* Second stage, for every template of this segment that fired, in one
       call.  Run one at a time it re-read the data spectrum per template and
       cost 4.65 us/pair against 2.76 us batched; the gate makes the fired set
       sparse and scattered, which is why ap_mf_run_sel takes an index list
       rather than a range. */
    if(nfire){
      if(!p->dready[d0+d]){
        if(ap_mf_set_data(p->full,d0+d,p->dspec[d0+d])) return -1;
        p->dready[d0+d]=1;
      }
      unsigned long long r0 = p->prof ? ap_ticks() : 0;
      int r=ap_mf_run_sel(p->full,d0+d,1,t0,nt,p->firebuf,nfire,
                          binsize,threshold,
                          peaks+(size_t)d*nt*nb,counts?counts+(size_t)d*nt:NULL,
                          start,end);
      if(p->prof) p->c_ref += ap_ticks()-r0;
      if(r<0) return -1;
      total+=r;
    }
  }
  return total;
}
