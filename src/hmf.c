/* matchedfilter: hierarchical matched filter.
 *
 * Most of a template's SNR lives in the low part of the band.  Correlate only
 * that part, on a coarse lag grid, and pay for the full correlation only where
 * the coarse result could still become a detection.
 *
 * The guarantee is one-sided: a reported peak is bit-identical to ap_mf_run's,
 * because when the coarse pass escalates this calls ap_mf_run.  Only omissions are
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
 * 3. The margin only needs |v|, and the re-modulation phase has unit magnitude,
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

#define HMF_IK 6            /* half-width of the bracket taps: 13 in all */
static void design_taps(const float *w, size_t m, int K, double delta, float *h);
static float interp_abs(const float *ev,const float *od,size_t m,int U,
                        const float *w,int K,int i,long j);

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
  float     *fwd,*spec;       /* [2n] block staging; spec is [dgroup][2n]        */
  ap_plan   *cf;              /* explicit m-point plan, for the rare interpolation
                                 path that needs the series materialised        */
  const float **dspec;        /* [nd]       caller's full spectra, ingested lazily */
  char *dready;               /* [nd]       1 once ingested into the full plan  */
  int dgroup;                 /* data segments filtered together; see create */
  float *ct0, *ct1;           /* [nt][2m]   coarse templates: even, half-shifted*/
  float *fpow;                /* [nt]       band power fraction per template    */
  /* Reference SNR distribution, or ref_on=0 to measure per template.  The
     output distribution is a property of the signal rather than of any one
     template, so one reference serves a whole bank -- and skips the
     per-template ingest measurement. */
  int    ref_on;
  float  even_margin, coarse_margin, gscale; int gcal;
  float  ref_f, ref_g, ref_graw, ref_graw1;
  float *tg,*tgraw,*tgraw1;   /* [nt]       per-template recovery factors       */
  float *shift;               /* [2m]       scratch for the measurement         */
  float *shift2;              /* [4m]       weighted template copies            */
  float *prod, *cev, *cod;    /* scratch: product and the two coarse halves     */
  float *taps;                /* [HMF_NSUB][K] complex interpolation bank       */
  /* Bracketing the odd transform.  ibuf holds one interpolated coarse maximum
     per template, produced alongside the even pass; ilo/ihi bound its ratio to
     the true combined maximum.  See docs/hierarchical.md. */
  float *ihlo, *ihhi;         /* [2*(2*IK+1)] complex taps, the two offsets */
  float *ibuf;                /* [nd*nt] */
  /* The interpolation taps are designed against the spectral shape of the
     product the coarse pass forms, |D|^2 |T|^2.  Neither factor may be
     assumed: the reference supplies the first and the caller's templates the
     second, so both are measured and the taps are rebuilt when either moves. */
  float *refpow, *tpow; int ntpow, taps_stale;
  float ilo, ihi; int ibrk, incand;
  float *tcbuf,*rawbuf,*evenbuf; /* [nt] per-template coarse thresholds, derived once a run */
  ap_peak *cebuf;             /* [nd*nt] even coarse maxima, whole batch */
  int *firebuf;               /* [nt] which templates fired, for one segment */
  long pairs, trig;
  /* Phase counters in cycles.  rdtsc, not clock_gettime: the latter costs
     ~25 ns and these phases are ~200 ns, so it would measure itself. */
  unsigned long long c_even,c_odd,c_ref,c_fill; int prof;
  long nbrk_fire,nbrk_rej;    /* pairs the bracket settled without the odd pass */
  FILE *dump;          /* MF_HMF_DUMP: per-pair (even, combined, margin) */
  long npre, ninterp, nskip;   /* diagnostics: pre-screen passes, interpolations run */
  float last_thr;
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
   wrong recovery factors and a margin far below where it belongs. */
static void prod_inter_nc(const float *d,const float *h,float *o,size_t m){
  for(size_t k=0;k<m;k++){
    float x=d[2*k],y=d[2*k+1],u=h[2*k],v=h[2*k+1];
    o[2*k]  = x*u + y*v;
    o[2*k+1]= x*v - y*u;
  }
}

/* Everything sized by the band, allocated as a unit.  The band itself is
   chosen by the Python class from the tuning table and handed in explicitly,
   so this only ever runs once, at construction. */
static int alloc_band_state(ap_hmf_plan *p,size_t band,int U,int K,
                            int ndi,int ntmpl){
  p->m=band; p->U=U; p->K=K;
  p->coarse =ap_mf_create(band,ndi,2*ntmpl);
  p->cf     =ap_create(band);
  p->ct0    =ap_alloc64((size_t)ntmpl*2*band*sizeof(float));
  p->ct1    =ap_alloc64((size_t)ntmpl*2*band*sizeof(float));
  p->shift  =ap_alloc64(2*band*sizeof(float));
  p->shift2 =ap_alloc64(4*band*sizeof(float));
  p->prod   =ap_alloc64(2*band*sizeof(float));
  p->cev    =ap_alloc64(2*band*sizeof(float));
  p->cod    =ap_alloc64(2*band*sizeof(float));
  p->taps   =ap_alloc64((size_t)2*HMF_NSUB*K*sizeof(float));
  p->refpow =calloc(band,sizeof(float));
  p->tpow   =calloc(band,sizeof(float));
  if(!p->coarse||!p->cf||!p->ct0||!p->ct1||!p->shift||!p->shift2||!p->prod||
     !p->cev||!p->cod||!p->taps||!p->refpow||!p->tpow) return -1;
  build_taps(p->taps,K,U);
  return 0;
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
  /* How many data segments to filter together.
   *
   * D x T is symmetric and the pair loop tiles both axes, so what matters is
   * the SHAPE of a batch, not its size: one segment against a large bank makes
   * the even coarse pass stream the whole coarse bank for T pairs and reuse
   * none of it.
   *
   * This used to be chosen from whether the coarse bank still fitted L2 -- 32
   * above, 4 below -- and that was right for the code it was measured on,
   * where every block also paid to ingest a full spectrum it almost never
   * used. Once that became lazy the cache effect went with it, and a large
   * group is now only a cost:
   *
   *     templates     g1      g4      g8     g16     g32
   *        37       1.149   1.136   1.126*  1.134   1.142
   *        74       1.133   1.087*  1.092   1.126   1.119
   *       128       1.104   1.056   1.049*  1.131   1.132
   *       256       1.209   1.146   1.117*  1.125   1.120
   *       418       1.180   1.119*  1.153   1.165   1.190
   *
   * 8 is best or within a percent of it at every size, so it is a constant
   * again. The caller should not have to know any of this, which is why it is
   * here and not in the API. */
  int grp = 8;
  { const char *e=getenv("MF_DGROUP"); if(e){ int v=atoi(e); if(v>0) grp=v; } }
  /* bounded by what the held spectra cost, which is what bites at long n */
  while(grp>1 && (size_t)grp*2*n*sizeof(float) > (size_t)4*1024*1024) grp>>=1;
  p->dgroup=grp;
  const int ndi = ndata>grp ? ndata : grp;
  p->nd=ndi; p->nt=ntmpl; p->snr=snr; p->fd=fd;
  p->full  =ap_mf_create(n,ndi,ntmpl);
  if(alloc_band_state(p,band,oversample,taps,ndi,ntmpl)){ ap_hmf_destroy(p); return NULL; }
  p->full_fft=ap_create(n);
  p->fwd =ap_alloc64(2*n*sizeof(float));
  p->spec=ap_alloc64((size_t)grp*2*n*sizeof(float));
  p->dspec=calloc((size_t)ndi,sizeof(*p->dspec));
  p->dready=calloc((size_t)ndi,1);
  p->fpow=calloc((size_t)ntmpl,sizeof(float));
  p->tg=calloc((size_t)ntmpl,sizeof(float));
  p->tgraw=calloc((size_t)ntmpl,sizeof(float));
  p->tgraw1=calloc((size_t)ntmpl,sizeof(float));
  p->tcbuf=calloc((size_t)ntmpl,sizeof(float));
  p->rawbuf=calloc((size_t)ntmpl,sizeof(float));
  p->evenbuf=calloc((size_t)ntmpl,sizeof(float));
  p->cebuf=calloc((size_t)ndi*ntmpl,sizeof(ap_peak));
  p->firebuf=calloc((size_t)ntmpl,sizeof(int));
  p->ihlo=calloc((size_t)2*(2*HMF_IK+1),sizeof(float));
  p->ihhi=calloc((size_t)2*(2*HMF_IK+1),sizeof(float));
  p->ibuf=calloc((size_t)ndi*ntmpl,sizeof(float));
  p->taps_stale=1;
  /* Bounds on the interpolated statistic against the true combined maximum.
     Derived on six captured segments and checked on six others, which violated
     at 0.19%, so they carry a margin -- only the lower one can lose a trigger;
     an over-report merely fires the coarse threshold for nothing. */
  /* The bracket is OFF.  It has been turned on and off three times; this is
     why it is off.
     
     It settles a pair without the odd coarse transform when the interpolated
     statistic's two-sided bound does not straddle the coarse threshold.  The reject side
     is sound only while ilo <= min(S/true)/graw over real triggers, and that
     minimum was MEASURED over the twelve captures -- 0.8384 at 9 taps, 0.8855
     at 13, saturating at 0.8931 by 17 -- giving a bound of 0.9121 at the 13
     taps HMF_IK=6 selects.  At ilo=0.90, inside that bound, it is a 2% win on
     the captures with 31/842 and 0/842 unchanged.
     
     It then lost a trigger on the first independent workload it met: the
     pycbc_inspiral_fir example at threshold 5.0 returns 893 triggers with the
     bracket off and 892 with it on, and is 4% SLOWER with it on (0.229 s
     against 0.220 s of kernel time).  The bound was derived from one dataset
     and does not transfer.  Backing ilo off to 0.86, conservative enough to be
     safe on both, makes it a loss on the captures too (10.63 ms against
     10.14).  So there is no setting that is both safe and profitable.
     
     What survives is a correct implementation behind MF_BRACKET=1 -- the
     vectorised interp_max it needs was dead code, plumbed through dispatch.c
     and never called, which is why it used to measure 5x slower -- and the
     soundness criterion above in place of a fitted constant. */
  p->ilo=0.90f; p->ihi=1.10f; p->ibrk=0; p->incand=16;   /* MF_BRACKET=1 enables */
  { const char *e;
    if((e=getenv("MF_BRACKET"))) p->ibrk=atoi(e);
    if((e=getenv("MF_BRACKET_LO"))) p->ilo=(float)atof(e);
    if((e=getenv("MF_BRACKET_HI"))) p->ihi=(float)atof(e);
    if((e=getenv("MF_BRACKET_C"))) p->incand=atoi(e); }
  if(!p->full||!p->coarse||!p->cf||!p->full_fft||!p->fwd||!p->spec||!p->dspec||!p->dready||!p->ct0||!p->ct1||!p->fpow||!p->tg||!p->tgraw||!p->tgraw1||!p->shift||!p->shift2||
     !p->prod||!p->cev||!p->cod||!p->taps||!p->tcbuf||!p->rawbuf||!p->evenbuf||!p->cebuf||!p->firebuf||!p->ihlo||!p->ihhi||!p->ibuf||!p->refpow||!p->tpow){ ap_hmf_destroy(p); return NULL; }
  /* Safety factor on the even-pass threshold, over and above the measured graw1.
     The realisation model is a power-law reference filtered by a matched
     template; the ratio filter's product is shaped differently, and on 12
     captured pycbc segments the real even/combined ratio reached 0.809 where
     the model says 0.897.  Swept against those captures over 811 triggers:
     0.92 and below lose nothing, 0.95 loses one (1.2e-3, already past the
     1e-3 budget) and 1.00 loses sixteen. */
  /* Scale on the coarse threshold the design table derives.  1.0 is that table's own
     answer, and on 12 captured pycbc segments it misses 31 of 842 real
     triggers -- 3.7%, and 13% for triggers within 0.5% of the threshold,
     against a 1e-3 budget.  0.94 recovers all of them, at 2.51x against the
     flat filter where 1.0 gives 3.32x.  The table's recovery factors are
     measured from a mean spectrum and are not a bound on a realisation; see
     docs/hierarchical.md.  Until that is fixed this is the honest control. */
  /* Automatic margin calibration, off by default.  It lands within 1.5% of the
     hand-tuned operating point, but the scale below is fitted, not derived:
     hmf_threshold already models the noise statistics, and taking a low
     quantile of the recovered signal peak counts that fluctuation a second
     time.  Until the double count is removed this is a re-parametrised knob,
     not a corrected model. */
  p->gcal=0; p->gscale=1.40f;
  { const char *e=getenv("MF_GSCALE"); if(e) p->gscale=(float)atof(e); }
  { const char *e=getenv("MF_GCAL"); if(e) p->gcal=atoi(e); }
  p->coarse_margin=1.0f;
  { const char *e=getenv("MF_GATE_MARGIN"); if(e) p->coarse_margin=(float)atof(e); }
  p->even_margin=0.92f;
  { const char *e=getenv("MF_EVEN_MARGIN"); if(e) p->even_margin=(float)atof(e); }
  p->prof = getenv("MF_HMF_PROF") ? 1 : 0;
  { const char *e=getenv("MF_HMF_DUMP"); p->dump = e ? fopen(e,"wb") : NULL; }
  return p;
}

/* There is no band-free constructor.  Choosing band, oversample and taps is
   the tuning tables' job, and they are measured; a compiled model that
   answered the same question was a second source of truth that could not be
   checked and did not promise the false-dismissal budget.  Callers either
   state the configuration or let the Python class read it from the tables,
   which refuses rather than guesses outside its coverage. */

void ap_hmf_destroy(ap_hmf_plan *p){
  if(!p) return;
  if(p->full) ap_mf_destroy(p->full);
  if(p->coarse) ap_mf_destroy(p->coarse);
  if(p->cf)   ap_destroy(p->cf);
  if(p->full_fft) ap_destroy(p->full_fft);
  free(p->fwd);free(p->spec);
  free(p->dspec);free(p->dready);free(p->ct0);free(p->ct1);free(p->fpow);
  if(p->dump) fclose(p->dump);
  free(p->ihlo);free(p->ihhi);free(p->ibuf);free(p->refpow);free(p->tpow);
  free(p->tg);free(p->tgraw);free(p->tgraw1);free(p->shift);free(p->shift2);
  free(p->prod);free(p->cev);free(p->cod);free(p->taps);free(p->tcbuf);free(p->rawbuf);free(p->evenbuf);free(p->cebuf);free(p->firebuf);
  free(p);
}

int ap_hmf_coarse_thresholds(ap_hmf_plan *p,float threshold,
                             float *margin,float *raw,float *even)
{
  if(!p) return -1;
  /* Exactly the derivation the run loop uses, so a backend that reads these
     makes the same decision rather than a similar one. Template 0 stands for
     all of them: with a reference set, fpow and the recovery factors come
     from the reference, so every template gets the same three numbers. */
  float T = p->fs_snr > 0.0f ? p->fs_snr
                             : (threshold>p->snr ? threshold : p->snr);
  float gt = p->tg[0];
  float tc = hmf_threshold(p->fpow[0]*gt*gt,T,p->fd)*p->coarse_margin;
  if(margin) *margin = tc;
  if(raw)    *raw    = tc*p->tgraw [0]*0.999f;
  if(even)   *even   = tc*p->tgraw1[0]*p->even_margin;
  return 0;
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
    fprintf(stderr,"    [diag] pairs=%ld pre-screen passes=%ld (%.1f/pair) "
            "interpolations=%ld (%.1f/pair) odd-skipped=%.1f%% margin=%.3f\n",
            p->pairs,p->npre,(double)p->npre/(p->pairs?p->pairs:1),
            p->ninterp,(double)p->ninterp/(p->pairs?p->pairs:1),
            100.0*p->nskip/(p->pairs?p->pairs:1),p->last_thr);
  if(getenv("MF_HMF_DIAG"))
    fprintf(stderr,"    [diag] bracket: fired %ld (%.1f%%) rejected %ld (%.1f%%) "
            "of %ld pairs\n", p->nbrk_fire,100.0*p->nbrk_fire/(p->pairs?p->pairs:1),
            p->nbrk_rej,100.0*p->nbrk_rej/(p->pairs?p->pairs:1),p->pairs);
}
void ap_hmf_config(const ap_hmf_plan *p,size_t *band,int *oversample,int *taps){
  if(!p) return;
  if(band) *band=p->m;
  if(oversample) *oversample=p->U;
  if(taps) *taps=p->K;
}

static void measure_recovery(ap_hmf_plan *p,int t,const float *a0,const float *a1,
                             float *gout,float *grawout,float *graw1out);

/* Scale on the coarse threshold, and the strongest lever there is: it trades trigger
   rate against dismissal directly, where band and oversample only do so
   through the statistic.  Read per run, so it applies at once. */
int ap_hmf_set_coarse_margin(ap_hmf_plan *p,float g){
  if(!p||!(g>0.f)) return -1;
  p->coarse_margin=g; return 0;
}
int ap_hmf_set_first_stage(ap_hmf_plan *p,float snr){
  if(!p) return -1;
  p->fs_snr = snr > 0.0f ? snr : 0.0f;   /* <=0 restores the derived level */
  return 0;
}

int ap_hmf_set_reference(ap_hmf_plan *p,const float *power){
  if(!p) return -1;
  if(!power){ p->ref_on=0; return 0; }
  /* Pick the band from this reference, now that we can see where the power
     is.  Only before any template has been ingested: templates are stored as
     coarse spectra at the current band, so re-choosing would invalidate them.
     Every caller sets the reference first, which is also the documented
     order. */
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
   * reach the coarse threshold, which needs a bound on even_max/combined_max.  Derived
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
       margin then opened on 70% of pairs.  A quantile needs enough samples to be
       a quantile. */
    const int K=128; const int K2=p->K;
    /* Noise levels to sweep.  The pairs this margin decides are the marginal
       ones, where the combined maximum is barely at the coarse threshold and may be a
       noise peak rather than the signal.  Simulating at one high SNR only
       ever reproduces the noiseless scallop, which is what the even-pass threshold is
       NOT allowed to assume. */
    /* Noise levels.  For graw1 -- a ratio of two maxima of the same series --
       the level barely matters, so a wide sweep was harmless.  For g and graw
       the reference is the SIGNAL's peak, and the guarantee is for a signal of
       strength snr, so the level has to put the peak there: any louder and the
       recovery is trivially 1, any quieter and the maximum is noise and the
       ratio is meaningless.  Peak is sum(amp); noise at a lag is
       nz*sqrt(2*sum(amp^2)); set their ratio to snr and spread a little. */
    double sa=0,sa2=0;
    for(size_t k=0;k<m;k++){ const double a=power[k]>0?power[k]:0; sa+=a; sa2+=a*a; }
    const double snr0=p->snr>0.f?(double)p->snr:5.0;
    const double nz0=(sa2>0&&snr0>0)?sa/(snr0*sqrt(2.0*sa2)):0.35;
    const double nzlev[4]={nz0*0.7,nz0,nz0*1.4,nz0*2.0};
    float *rat=malloc((size_t)K*sizeof(float));
    /* The same realisations also bound what the filter recovers of a SIGNAL,
       which is what the final margin needs.  measure_recovery derives g and graw
       from a noiseless autocorrelation, and that is a mean shape rather than a
       bound on any realisation -- the same error that made graw1 wrong.  The
       reference is the signal's own peak, sum over the band of the product's
       amplitude, which is what all phases aligning gives. */
    float *ratg=malloc((size_t)K*sizeof(float));
    float *ratr=malloc((size_t)K*sizeof(float));
    double pk=0; for(size_t k=0;k<m;k++) pk+=power[k]>0?power[k]:0;
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
      /* combined-grid and interpolated recovery of the signal's peak */
      { long bj=0; float bv=-1.f;
        const int UU=p->U;
        const size_t G=m*(size_t)UU;
        for(size_t j=0;j<G;j++){
          const float *z=(UU==1)?p->cev+2*j:((j&1)?p->cod+((j>>1)*2):p->cev+((j>>1)*2));
          const float v=z[0]*z[0]+z[1]*z[1];
          if(v>bv){ bv=v; bj=(long)j; }
        }
        const float ball=sqrtf(bv>0?bv:0);
        float bi=ball;
        for(int i=0;i<HMF_NSUB;i++){
          const float u1=interp_abs(p->cev,p->cod,m,p->U,p->taps,K2,i,bj-1);
          const float u2=interp_abs(p->cev,p->cod,m,p->U,p->taps,K2,i,bj);
          if(u1>bi) bi=u1;
          if(u2>bi) bi=u2;
        }
        ratr[r] = pk>0 ? (float)(ball/pk) : 1.f;
        ratg[r] = pk>0 ? (float)(bi/pk)   : 1.f;
      }
    }
    /* low quantile: second smallest of 128 is about the 1% point */
    for(int i=0;i<3;i++)
      for(int j=i+1;j<K;j++)
        if(rat[j]<rat[i]){ float t=rat[i]; rat[i]=rat[j]; rat[j]=t; }
    /* low quantile of each, then keep whichever is more conservative */
    for(int i=0;i<3;i++) for(int j=i+1;j<K;j++){
      if(ratg[j]<ratg[i]){ float t=ratg[i]; ratg[i]=ratg[j]; ratg[j]=t; }
      if(ratr[j]<ratr[i]){ float t=ratr[i]; ratr[i]=ratr[j]; ratr[j]=t; }
    }
    const float g_noiseless=p->ref_g, r_noiseless=p->ref_graw;
    if(p->gcal){
      /* The realisation reference is the noiseless signal amplitude, so this
         ratio also carries the peak's own noise fluctuation -- which is not a
         grid loss and moves the coarse and full statistics together.  Scale
         controls how much of it to believe while that is sorted out. */
      const float gs=p->gscale;
      if(ratg[1]*gs<p->ref_g)    p->ref_g   =ratg[1]*gs>1.f?1.f:ratg[1]*gs;
      if(ratr[1]*gs<p->ref_graw) p->ref_graw=ratr[1]*gs>1.f?1.f:ratr[1]*gs;
    }
    if(getenv("MF_HMF_DIAG"))
      fprintf(stderr,"    [diag] g: noiseless %.4f realisations %.4f -> %.4f | "
              "graw: noiseless %.4f realisations %.4f -> %.4f\n",
              g_noiseless,ratg[1],p->ref_g,r_noiseless,ratr[1],p->ref_graw);
    float q=rat[1];
    if(getenv("MF_HMF_DIAG"))
      fprintf(stderr,"    [diag] graw1: scallop %.4f  realisations %.4f -> %.4f\n",
              p->ref_graw1, q, q<p->ref_graw1?q:p->ref_graw1);
    if(q<p->ref_graw1) p->ref_graw1=q;
    free(rat); free(ratg); free(ratr);
  }
  for(size_t k=0;k<m;k++) p->refpow[k]=power[k]>0?power[k]:0.f;
  p->taps_stale=1;
  p->ref_on=1;
  return 0;
}

int ap_hmf_set_data(ap_hmf_plan *p,int d,const float *spec){
  if(!p||d<0||d>=p->nd) return -1;
  /* The FULL plan's ingest is a group-major transpose of n complex, and the
     margin discards it on the overwhelming majority of pairs -- 99.9% at a 0.1%
     trigger rate.  Keep the caller's pointer instead and ingest lazily, the
     first time a pair on this data segment actually reaches refinement.  The
     spectrum must stay valid until run() returns, which is already the
     contract: set_data then run. */
  p->dspec[d]=spec;
  p->dready[d]=0;
  /* The coarse band IS the first 2m floats of the spectrum, so the interleaved
     copy this used to keep was the same bytes at a second address.  The rare
     refinement path reads them through dspec instead; the spectrum has to stay
     valid until run() returns either way, which is what the lazy full ingest
     above already depends on. */
  if(ap_mf_set_data(p->coarse,d,spec)) return -1;   /* only the kept band */
  return 0;
}

static float interp_abs(const float *ev,const float *od,size_t m,int U,
                        const float *w,int K,int i,long j);

/* Least-squares taps for a half-sample shift of the coarse series.
 *
 * We need h with  sum_i h_i exp(2i pi k i/m) = exp(2i pi k delta/m)  over the
 * band.  Truncating the ideal kernel solves this badly: the band is a
 * rectangle so the kernel decays as 1/y.  Solving the weighted problem
 * directly is better by about 2x at every length, and the weight is known --
 * the product D conj(T) carries power[k], so |P|^2 goes as power^2.
 *
 * The normal equations are Hermitian Toeplitz, built from c[d] = sum_k w_k
 * exp(2i pi k d/m); the right-hand side is the same sum at a fractional
 * argument.  Solved by plain elimination: it is (2K+1) square, once per
 * reference.
 */
static void design_taps(const float *w, size_t m, int K, double delta, float *h)
{
  const int N = 2*K + 1;
  double ar[2*HMF_IK+1][2*(2*HMF_IK+1)+2];   /* [row][2*col] real/imag, +rhs */
  double cr[4*HMF_IK+1], ci[4*HMF_IK+1];
  for (int d = -2*K; d <= 2*K; d++) {
    double sr = 0, si = 0;
    for (size_t k = 0; k < m; k++) {
      const double a = 2.0*M_PI*(double)k*d/(double)m;
      sr += w[k]*cos(a); si += w[k]*sin(a);
    }
    cr[d+2*K] = sr; ci[d+2*K] = si;
  }
  for (int i = 0; i < N; i++) {
    for (int j = 0; j < N; j++) {
      const int d = (j-K) - (i-K);
      ar[i][2*j]   = cr[d+2*K];
      ar[i][2*j+1] = ci[d+2*K];
    }
    double sr = 0, si = 0;
    for (size_t k = 0; k < m; k++) {
      const double a = 2.0*M_PI*(double)k*(delta - (i-K))/(double)m;
      sr += w[k]*cos(a); si += w[k]*sin(a);
    }
    ar[i][2*N] = sr; ar[i][2*N+1] = si;
  }
  /* complex Gaussian elimination with partial pivoting */
  for (int c = 0; c < N; c++) {
    int piv = c; double best = 0;
    for (int r = c; r < N; r++) {
      const double v = ar[r][2*c]*ar[r][2*c] + ar[r][2*c+1]*ar[r][2*c+1];
      if (v > best) { best = v; piv = r; }
    }
    if (best <= 0) { for (int i = 0; i < 2*N; i++) h[i] = 0.f; return; }
    if (piv != c) for (int j = 0; j <= 2*N+1; j++) {
      const double t = ar[c][j]; ar[c][j] = ar[piv][j]; ar[piv][j] = t; }
    const double pr = ar[c][2*c], pi_ = ar[c][2*c+1], pm = pr*pr + pi_*pi_;
    for (int r = 0; r < N; r++) {
      if (r == c) continue;
      const double xr = ar[r][2*c], xi = ar[r][2*c+1];
      const double fr = (xr*pr + xi*pi_)/pm, fi = (xi*pr - xr*pi_)/pm;
      if (fr == 0 && fi == 0) continue;
      for (int j = c; j <= N; j++) {
        const double br = ar[c][2*j], bi = ar[c][2*j+1];
        ar[r][2*j]   -= fr*br - fi*bi;
        ar[r][2*j+1] -= fr*bi + fi*br;
      }
    }
  }
  for (int i = 0; i < N; i++) {
    const double pr = ar[i][2*i], pi_ = ar[i][2*i+1], pm = pr*pr + pi_*pi_;
    const double xr = ar[i][2*N], xi = ar[i][2*N+1];
    h[2*i]   = (float)((xr*pr + xi*pi_)/pm);
    h[2*i+1] = (float)((xi*pr - xr*pi_)/pm);
  }
}



/* Measure this template's own recovery factors instead of inheriting the
 * table's.
 *
 * The table's figures were measured on the design template (85% of its power in
 * the lowest n/8 bins).  Recovery depends on the spectral shape *inside* the
 * kept band -- a flatter template has a sharper correlation peak and recovers
 * less -- so a caller whose templates differ would have coarse thresholds calibrated for a
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
     the true figure was 0.958: the even-pass threshold was then ~4% too high and every
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
     1 would raise the coarse threshold above what the statistics justify. */
  *gout     = gi>1.f?1.f:gi;
  *grawout  = gr>1.f?1.f:gr;
  *graw1out = g1>1.f?1.f:g1;
}

int ap_hmf_set_template(ap_hmf_plan *p,int t,const float *spec){
  if(!p||t<0||t>=p->nt) return -1;
  if(ap_mf_set_template(p->full,t,spec)) return -1;
  const size_t n=p->n,m=p->m;
  /* Band power fraction decides the coarse threshold: rho_c = sqrt(f)*rho_full + noise, so
     f is what sets how far the coarse value sits below the full one.  It varies
     per template, so the threshold has to as well - one global margin would be
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
     would mis-scale the coarse output and shift the coarse threshold off calibration. */
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
  { /* accumulate the supplied template's band shape; the taps are designed
       against it rather than against any assumption about its form */
    if(p->ntpow==0) for(size_t k=0;k<m;k++) p->tpow[k]=0.f;
    for(size_t k=0;k<m;k++) p->tpow[k]+=(float)(a0[2*k]*a0[2*k]+a0[2*k+1]*a0[2*k+1]);
    p->ntpow++; p->taps_stale=1; }
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
  const size_t nb0=ap_mf_nbins(p->full,binsize,win_start[0],win_end[0]);
  int total=0;
  /* Filter several blocks together where they share a window.  Blocks differ
     only at a segment's edges, so runs of equal windows are long. */
  for(int b0=0;b0<nblocks;){
    int g=1;
    while(g<p->dgroup && b0+g<nblocks
          && win_start[b0+g]==win_start[b0] && win_end[b0+g]==win_end[b0]) g++;
    for(int j=0;j<g;j++){
      const size_t s0=start[b0+j];
      size_t have = s0<nseries ? nseries-s0 : 0;
      if(have>n) have=n;
      /* pycbc's inverse is unnormalised and so is matchedfilter's, so the
         caller's convention of pre-dividing the block spectrum by n is kept.
         Doing it on the way IN rather than to the result folds it into a copy
         that has to happen anyway and removes a separate pass over 2n floats
         -- 12% of the per-block cost, which is itself 12% of the total at 37
         templates.  n is a power of two, so 1/n is exact and the transform is
         linear: scaling before is bit-for-bit the same as scaling after, which
         the fixtures check by reproducing pycbc's SNRs to 0.0e+00. */
      { const float inv=1.0f/(float)n;
        const float *src=series+2*s0;
        for(size_t k=0;k<2*have;k++) p->fwd[k]=src[k]*inv; }
      if(have<n) memset(p->fwd+2*have,0,2*(n-have)*sizeof(float));
      float *const sp=p->spec+(size_t)j*2*n;
      ap_fft(p->full_fft,p->fwd,sp,AP_FORWARD);
      if(ap_hmf_set_data(p,j,sp)) return -1;
      /* The full spectrum is NOT ingested here.  Only the coarse band is read
         by every pair; the full one is read only when a pair fires, which at
         threshold 5.5 is 0.1% of pairs and so about 4% of blocks.  Ingesting
         it eagerly costs 0.4-1.0 us a block for nothing on the rest.  What
         forced it was that one staging buffer was reused by the next block,
         so set_data's retained pointer went stale; giving the group a buffer
         per slot removes that and lets ap_hmf_run's existing lazy path do it
         on demand.  dready stays 0 to say so. */
    }
    size_t nb=ap_mf_nbins(p->full,binsize,win_start[b0],win_end[b0]);
    /* peaks is addressed at a single stride, so every window must produce the
       same bin count. A shorter one at a segment's edge does not: it writes
       where the next block's row begins and runs off the end of the caller's
       buffer -- heap corruption from ordinary overlap-save input, since edge
       blocks are exactly the ragged ones this call exists to accept.
       Refusing is the honest answer; the shape the API returns has one nbins
       in it and cannot express two. */
    if(nb!=nb0) return -1;
    int r=ap_hmf_run(p,0,g,t0,nt,binsize,threshold,
                     peaks+(size_t)b0*nt*nb,counts?counts+(size_t)b0*nt:NULL,
                     win_start[b0],win_end[b0]);
    if(r<0) return -1;
    total+=r;
    b0+=g;
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
  /* Recalibrate the coarse threshold for the weakest signal that can actually be REPORTED,
     which is max(snr, threshold).  Two wrong ways to do this:
       - margin at max(tc, threshold): raises the coarse threshold above what snr calibrated,
         so it dismisses at a rate the design never bounded.
       - margin at tc alone when threshold > snr: correct but wasteful, since
         signals between snr and threshold are discarded by the full filter
         anyway, and calibrating for them only opens the coarse threshold needlessly.
     Both the threshold and snr are in units where the noise has unit-variance
     components, which is the caller's pre-normalisation contract. */
  /* All three coarse thresholds depend only on the template, so derive them once per run
     rather than per pair.  With D data segments and T templates the pair loop
     runs D*T times and this runs T times: the whole point of the D x T shape is
     that anything one-sided belongs outside the product. */
  if(p->ibrk && p->taps_stale && p->ntpow>0){
    float *w=malloc(m*sizeof(float));
    if(w){
      const float inv=1.0f/(float)p->ntpow;
      for(size_t k=0;k<m;k++) w[k]=p->refpow[k]*p->tpow[k]*inv;
      design_taps(w,m,HMF_IK,-0.5,p->ihlo);
      design_taps(w,m,HMF_IK, 0.5,p->ihhi);
      free(w);
      ap_mf_set_interp(p->coarse,p->ihlo,p->ihhi,2*HMF_IK+1,p->incand,p->ibuf);
      p->taps_stale=0;
    }
  }
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
      tcs[t]=hmf_threshold(p->fpow[t0+t]*gt*gt,T,p->fd)*p->coarse_margin;
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
     sweep, and consecutive transforms are no longer separated by the coarse threshold
     branch, so they can overlap.  One threshold has to serve every template, so
     use the lowest: a template whose own margin is higher is filtered below, and
     a lower threshold only ever reports MORE peaks. */
  float minev=eveng[0];
  for(int t=1;t<nt;t++) if(eveng[t]<minev) minev=eveng[t];
  int total=0;
  { unsigned long long _eb = p->prof ? ap_ticks() : 0;
    if(ap_mf_run(p->coarse,d0,nd,t0,nt,cspan,minev,p->cebuf,NULL,
                 cstart,cend)<0) return -1;
    if(p->prof) p->c_even += ap_ticks()-_eb; } /* batched: charged to the batch */
  for(int d=0;d<nd;d++){
    const float *Dc=p->dspec[d0+d];      /* coarse band = its first 2m */
    int nfire=0;
    for(int t=0;t<nt;t++){
      const size_t row=(size_t)d*nt+t;
      p->pairs++;
      const float margin = tcs[t]; p->last_thr=margin;
      const float raw_thr  = rawg[t];
      int fire=0;
      /* Fused coarse pass: product, transform and maximum in one kernel, with
       * the product never reaching memory.  One bin spanning the whole coarse
       * window means the reported peak IS the maximum, so the separate scan
       * that used to walk the materialised series disappears entirely.
       * Threshold at raw_thr: below it, interpolation cannot reach the coarse threshold,
       * so ap_mf_run returns index<0 and there is nothing more to do. */
      ap_peak ce,co; int cc=0;
      co.index=-1; co.magnitude=0.f;
      /* Even half first, thresholded at graw1*margin rather than graw*margin.  The
       * even samples alone are the U=1 series, so if their maximum falls below
       * graw1*margin the true continuous peak cannot reach the coarse threshold no matter
       * what the odd samples hold - and the odd transform, half the coarse
       * cost, is skipped outright.  On noise that is the overwhelming majority
       * of pairs.  It must be graw1 and not graw: graw describes the combined
       * U=2 grid, which recovers more, so using it here would cut off peaks the
       * odd half would have found. */
      const float even_thr = eveng[t];
      unsigned long long _t0 = p->prof ? ap_ticks() : 0;
      ce = p->cebuf[(size_t)d*nt+t];
      if(ce.index>=0 && ce.magnitude<even_thr) ce.index=-1;   /* per-template margin */
      if(ce.index<0){
        if(getenv("MF_HMF_TRACE") && p->pairs<6)
          fprintf(stderr,"    [trace] pair=%ld margin=%.3f even_thr=%.3f "
                  "even max BELOW even_thr\n",p->pairs,margin,even_thr);
                                            /* cannot reach the coarse threshold: done */
        p->nskip++;
        goto verdict;
      }
      /* Bracket the odd transform.  The interpolated statistic S bounds the
         combined maximum on both sides, and a bracket that does not straddle
         the coarse threshold settles the pair without paying for the transform.  Every
         pair it cannot settle still gets the transform, so the reported
         triggers are unchanged. */
      if(p->ibrk==1 && U>1){
        const float S=p->ibuf[(size_t)d*nt+t];
        float lower=S/p->ihi;
        if(ce.magnitude>lower) lower=ce.magnitude;   /* exact, and free */
        if(lower>=margin){ fire=1; p->nbrk_fire++; goto verdict; }
        if(S/p->ilo<raw_thr){ p->nbrk_rej++; goto verdict; }
      }
      if(U>1){
        ap_mf_interp_pause(p->coarse,1);
        int rr=ap_mf_run(p->coarse,d0+d,1,p->nt+t0+t,1,cspan,raw_thr,&co,&cc,
                         cstart,cend);
        ap_mf_interp_pause(p->coarse,0);
        if(rr<0) return -1;
      }
      if(p->prof){ unsigned long long t1=ap_ticks(); p->c_odd+=t1-_t0; _t0=t1; }
      float bestmag = ce.magnitude>co.magnitude ? ce.magnitude : co.magnitude;
      /* The pair id is part of the record.  Without it a reader has to match
         rows by their even value, which is ambiguous whenever two pairs land
         close together -- and that ambiguity is indistinguishable from a
         mirror that computes the wrong thing. */
      if(p->dump){ float rec[8]={ce.magnitude,co.magnitude,bestmag,margin,
                                 raw_thr,even_thr,
                                 (float)(d0+d),(float)(t0+t)};
                   fwrite(rec,sizeof rec,1,p->dump); }
      if(getenv("MF_HMF_TRACE") && p->pairs<6)
        fprintf(stderr,"    [trace] pair=%ld margin=%.3f even_thr=%.3f "
                "coarse max=%.3f (even %.3f odd %.3f)\n",
                p->pairs,margin,even_thr,bestmag,ce.magnitude,co.magnitude);
      fire = bestmag>=margin;
      if(!fire && bestmag>=raw_thr){
        /* Rare: the raw maximum sits in [graw*margin, margin), the only window where
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
          if(interp_abs(p->cev,p->cod,m,U,p->taps,K,i,bestj-1) >= margin) fire=1;
          else if(interp_abs(p->cev,p->cod,m,U,p->taps,K,i,bestj) >= margin) fire=1;
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
       cost 4.65 us/pair against 2.76 us batched; the coarse threshold makes the fired set
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
