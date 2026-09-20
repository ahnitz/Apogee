/* peakfft: batched matched filter.
 *
 * D data segments x T templates, reporting the binned maximum of each pair's
 * correlation.  See docs/matched-filter-plan.md for where the time goes and which
 * reuse opportunities are real.
 *
 * Round 0 is deliberately the obvious implementation: form the product, hand it
 * to the existing backward binned-max path.  It exists so the test suite is
 * meaningful before any of the interesting optimisations go in, and so each of
 * those can be A/B'd against something known-correct.
 */
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "peakfft.h"

struct pf_mf_plan {
  size_t n;
  int nd, nt;
  pf_plan *fft;        /* shared transform plan: forward at ingest, backward per pair */
  float *dspec;        /* [nd][2n] forward spectra of the data segments   */
  float *tspec;        /* [nt][2n] forward spectra of the templates, ALREADY conjugated */
  float *prod;         /* scratch for one product                          */
};

pf_mf_plan *pf_mf_create(size_t n, int ndata, int ntmpl){
  if(ndata<1||ntmpl<1) return NULL;
  pf_mf_plan *p = calloc(1,sizeof(*p));
  if(!p) return NULL;
  p->n=n; p->nd=ndata; p->nt=ntmpl;
  p->fft = pf_create(n);
  if(!p->fft){ free(p); return NULL; }
  p->dspec = aligned_alloc(64,(size_t)ndata*2*n*sizeof(float));
  p->tspec = aligned_alloc(64,(size_t)ntmpl*2*n*sizeof(float));
  p->prod  = aligned_alloc(64,2*n*sizeof(float));
  if(!p->dspec||!p->tspec||!p->prod){ pf_mf_destroy(p); return NULL; }
  return p;
}

void pf_mf_destroy(pf_mf_plan *p){
  if(!p) return;
  if(p->fft) pf_destroy(p->fft);
  free(p->dspec); free(p->tspec); free(p->prod);
  free(p);
}

size_t pf_mf_nbins(const pf_mf_plan *p, size_t binsize, size_t start, size_t end){
  if(!p||!binsize) return 0;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  return (end-start+binsize-1)/binsize;
}

int pf_mf_set_data(pf_mf_plan *p, int d, const float *seg){
  if(!p||d<0||d>=p->nd) return -1;
  pf_fft(p->fft, seg, p->dspec+(size_t)d*2*p->n, PF_FORWARD);
  return 0;
}

int pf_mf_set_template(pf_mf_plan *p, int t, const float *tmpl){
  if(!p||t<0||t>=p->nt) return -1;
  float *h = p->tspec+(size_t)t*2*p->n;
  pf_fft(p->fft, tmpl, h, PF_FORWARD);
  /* conjugate once here rather than once per pair - the pair loop runs D times
     more often than this does */
  for(size_t k=0;k<p->n;k++) h[2*k+1] = -h[2*k+1];
  return 0;
}

int pf_mf_run(pf_mf_plan *p, int d0, int nd, int t0, int nt,
              size_t binsize, float threshold,
              pf_peak *peaks, int *counts, size_t start, size_t end){
  if(!p||nd<1||nt<1||!binsize) return 0;
  if(d0<0||d0+nd>p->nd||t0<0||t0+nt>p->nt) return -1;
  if(end>p->n) end=p->n;
  if(start>=end) return 0;
  const size_t n=p->n, nb=(end-start+binsize-1)/binsize;
  int total=0;
  for(int d=0;d<nd;d++){
    const float *D = p->dspec+(size_t)(d0+d)*2*n;
    for(int t=0;t<nt;t++){
      const float *H = p->tspec+(size_t)(t0+t)*2*n;   /* already conjugated */
      for(size_t k=0;k<n;k++){
        float ar=D[2*k], ai=D[2*k+1], br=H[2*k], bi=H[2*k+1];
        p->prod[2*k]   = ar*br - ai*bi;
        p->prod[2*k+1] = ar*bi + ai*br;
      }
      size_t row=(size_t)d*nt+t;
      int c[1];
      int r = pf_binmax(p->fft, p->prod, n, 1, binsize, threshold,
                        peaks+row*nb, c, PF_BACKWARD, start, end);
      if(r<0) return -1;
      if(counts) counts[row]=c[0];
      total += c[0];
    }
  }
  return total;
}
