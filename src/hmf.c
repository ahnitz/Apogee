/* Hierarchical matched filter: raw coarse maximum, then full refinement.
 * Calibration is supplied by the caller. No statistical model or recovery
 * fallback is compiled into this execution engine.
 */
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdio.h>
#include "ticks.h"
#include "alloc.h"
#include "matchedfilter.h"
#include "transform.h"

struct ap_hmf_plan {
  size_t n,m;
  int nd,nt,K,dgroup;
  ap_mf_plan *full,*coarse;
  ap_plan *full_fft;
  float *fwd,*spec;
  const float **dspec;
  char *dready,*tready;
  float *ct0,*scratch,*fpow;
  int ref_on;
  float ref_f,cal_thr;
  ap_peak *cebuf;
  int *firebuf;
  long pairs,trig;
  unsigned long long c_even,c_odd,c_ref,c_fill;
  int prof,trace;
  FILE *dump;
};

ap_hmf_plan *ap_hmf_create_ex(size_t n,int ndata,int ntmpl,float snr,float fd,
                              size_t band,int taps){
  (void)snr; (void)fd;
  if(ndata<1||ntmpl<1||!ap_supported(n)||!ap_supported(band)||band>=n
     ||taps<2||taps>64||(taps&1)) return NULL;
  ap_hmf_plan *p=calloc(1,sizeof(*p));
  if(!p) return NULL;
  p->n=n; p->m=band; p->nt=ntmpl; p->K=taps;
  /* Preserve the measured series grouping; the environment is diagnostic. */
  int grp = 8;
  { const char *e=getenv("MF_DGROUP"); if(e){ int v=atoi(e); if(v>0) grp=v; } }
  /* bounded by what the held spectra cost, which is what bites at long n */
  while(grp>1 && (size_t)grp*2*n*sizeof(float) > (size_t)4*1024*1024) grp>>=1;
  p->dgroup=grp; p->nd=ndata>grp ? ndata : grp;
  p->full=ap_mf_create(n,p->nd,ntmpl);
  p->coarse=ap_mf_create(band,p->nd,ntmpl);
  p->full_fft=ap_create(n);
  p->fwd=ap_alloc64(2*n*sizeof(float));
  p->spec=ap_alloc64((size_t)grp*2*n*sizeof(float));
  p->dspec=calloc((size_t)p->nd,sizeof(*p->dspec));
  p->dready=calloc((size_t)p->nd,1);
  p->tready=calloc((size_t)ntmpl,1);
  p->ct0=ap_alloc64((size_t)ntmpl*2*band*sizeof(float));
  p->scratch=ap_alloc64(2*band*sizeof(float));
  p->fpow=calloc((size_t)ntmpl,sizeof(float));
  p->cebuf=calloc((size_t)p->nd*ntmpl,sizeof(ap_peak));
  p->firebuf=calloc((size_t)ntmpl,sizeof(int));
  p->cal_thr=-1;
  if(!p->full||!p->coarse||!p->full_fft||!p->fwd||!p->spec||!p->dspec
     ||!p->dready||!p->tready||!p->ct0||!p->scratch||!p->fpow||!p->cebuf||!p->firebuf){
    ap_hmf_destroy(p); return NULL;
  }
  p->prof=getenv("MF_HMF_PROF")!=NULL;
  p->trace=getenv("MF_HMF_TRACE")!=NULL;
  const char *dump=getenv("MF_HMF_DUMP");
  p->dump=dump ? fopen(dump,"wb") : NULL;
  return p;
}

void ap_hmf_destroy(ap_hmf_plan *p){
  if(!p) return;
  ap_mf_destroy(p->full); ap_mf_destroy(p->coarse); ap_destroy(p->full_fft);
  free(p->fwd); free(p->spec); free(p->dspec); free(p->dready); free(p->tready);
  free(p->ct0); free(p->scratch); free(p->fpow); free(p->cebuf); free(p->firebuf);
  if(p->dump) fclose(p->dump);
  free(p);
}

int ap_hmf_coarse_thresholds(ap_hmf_plan *p,float threshold,float *thr){
  (void)threshold;
  if(!p || !isfinite(p->cal_thr) || p->cal_thr<0) return -1;
  if(thr) *thr=p->cal_thr;
  return 0;
}
size_t ap_hmf_nbins(const ap_hmf_plan *p,size_t bs,size_t lo,size_t hi){
  return p ? ap_mf_nbins(p->full,bs,lo,hi) : 0;
}
void ap_hmf_stats(const ap_hmf_plan *p,long *pairs,long *triggers){
  if(!p) return;
  if(pairs) *pairs=p->pairs;
  if(triggers) *triggers=p->trig;
  if(p->prof && p->pairs){
    double total=(double)(p->c_even+p->c_odd+p->c_ref+p->c_fill);
    fprintf(stderr,"    [prof] cycles/pair: even=%.0f (%.0f%%) gate=%.0f (%.0f%%) refine=%.0f (%.0f%%) fill=%.0f (%.0f%%)\n",
      (double)p->c_even/p->pairs,100*p->c_even/total,
      (double)p->c_odd/p->pairs,100*p->c_odd/total,
      (double)p->c_ref/p->pairs,100*p->c_ref/total,
      (double)p->c_fill/p->pairs,100*p->c_fill/total);
  }
}
void ap_hmf_config(const ap_hmf_plan *p,size_t *band,int *taps){
  if(!p) return;
  if(band) *band=p->m;
  if(taps) *taps=p->K;
}
int ap_hmf_set_threshold(ap_hmf_plan *p,float value){
  if(!p || !isfinite(value)) return -1;
  p->cal_thr=value; return 0; /* negative explicitly marks unconfigured */
}
int ap_hmf_set_first_stage(ap_hmf_plan *p,float snr){
  (void)snr;
  if(!p) return -1;
  p->cal_thr=-1; /* caller must supply the recalibrated threshold */
  return 0;
}
static int refresh_template(ap_hmf_plan *p,int t){
  double f=p->ref_on ? p->ref_f : p->fpow[t];
  double scale=f>0 ? 1/sqrt(f) : 0;
  const float *original=p->ct0+(size_t)t*2*p->m;
  for(size_t k=0;k<2*p->m;k++) p->scratch[k]=(float)(original[k]*scale);
  return ap_mf_set_template(p->coarse,t,p->scratch);
}
int ap_hmf_set_reference(ap_hmf_plan *p,const float *power){
  if(!p) return -1;
  if(power){
    double total=0,low=0;
    for(size_t k=0;k<p->n;k++){
      if(!isfinite(power[k]) || power[k]<0) return -1;
      total+=power[k]; if(k<p->m) low+=power[k];
    }
    if(total<=0) return -1;
    p->ref_f=(float)(low/total); p->ref_on=1;
  } else p->ref_on=0;
  for(int t=0;t<p->nt;t++) if(p->tready[t] && refresh_template(p,t)) return -1;
  return 0;
}
int ap_hmf_set_data(ap_hmf_plan *p,int d,const float *spec){
  if(!p||d<0||d>=p->nd||!spec) return -1;
  p->dspec[d]=spec; p->dready[d]=0;
  return ap_mf_set_data(p->coarse,d,spec);
}
int ap_hmf_set_template(ap_hmf_plan *p,int t,const float *spec){
  if(!p||t<0||t>=p->nt||!spec) return -1;
  if(ap_mf_set_template(p->full,t,spec)) return -1;
  double total=0,low=0;
  for(size_t k=0;k<p->n;k++){
    double re=spec[2*k],im=spec[2*k+1],power=re*re+im*im;
    total+=power; if(k<p->m) low+=power;
  }
  p->fpow[t]=total>0 ? (float)(low/total) : 0;
  memcpy(p->ct0+(size_t)t*2*p->m,spec,2*p->m*sizeof(float));
  p->tready[t]=1;
  return refresh_template(p,t);
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
        const float *src=have ? series+2*s0 : series;
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
  const size_t n=p->n,m=p->m;
  const size_t nb=ap_mf_nbins(p->full,binsize,start,end);

  if(!isfinite(p->cal_thr) || p->cal_thr < 0) return -1;
  /* Coarse sample j maps to full lag j*R. Widen by one coarse sample
     so rounding the caller's window remains conservative. */
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
  const float minev=p->cal_thr;
  int total=0;
  { unsigned long long _eb = p->prof ? ap_ticks() : 0;
    if(ap_mf_run(p->coarse,d0,nd,t0,nt,cspan,minev,p->cebuf,NULL,
                 cstart,cend)<0) return -1;
    if(p->prof) p->c_even += ap_ticks()-_eb; } /* batched: charged to the batch */
  for(int d=0;d<nd;d++){
    int nfire=0;
    for(int t=0;t<nt;t++){
      const size_t row=(size_t)d*nt+t;
      p->pairs++;
      const float thr = p->cal_thr;
      int fire=0;
      /* Fused coarse pass: product, transform and maximum in one kernel, with
       * the product never reaching memory.  One bin spanning the whole coarse
       * window means the reported peak IS the maximum, so the separate scan
       * that used to walk the materialised series disappears entirely. */
      ap_peak ce;
      unsigned long long _t0 = p->prof ? ap_ticks() : 0;
      ce = p->cebuf[(size_t)d*nt+t];
      if(ce.index>=0 && ce.magnitude<thr) ce.index=-1;
      if(ce.index<0){
        if(p->trace && p->pairs<6)
          fprintf(stderr,"    [trace] pair=%ld thr=%.3f coarse max BELOW thr\n",
                  p->pairs,thr);
        goto verdict;
      }
      if(p->prof){ unsigned long long t1=ap_ticks(); p->c_odd+=t1-_t0; _t0=t1; }
      const float bestmag = ce.magnitude;
      /* The pair id is part of the record.  Without it a reader has to match
         rows by their coarse value, which is ambiguous whenever two pairs land
         close together -- and that ambiguity is indistinguishable from a
         mirror that computes the wrong thing. */
      if(p->dump){ float rec[8]={ce.magnitude,0.0f,bestmag,thr,
                                 thr,thr,
                                 (float)(d0+d),(float)(t0+t)};
                   fwrite(rec,sizeof rec,1,p->dump); }
      if(p->trace && p->pairs<6)
        fprintf(stderr,"    [trace] pair=%ld thr=%.3f coarse max=%.3f\n",
                p->pairs,thr,bestmag);
      fire = bestmag>=thr;
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
        /* No spectrum was ever handed to this slot. ap_hmf_set_data stores
           the CALLER'S pointer and the refine path is the first thing to
           dereference it, so a run() with no set_data() reached here with
           NULL and segfaulted -- and only when a pair actually fired, which
           made it look intermittent. Refuse instead. */
        if(!p->dspec[d0+d]) return -1;
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
