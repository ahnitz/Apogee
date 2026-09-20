/* Hierarchical filter: the guarantee is one-sided, so that is what gets tested.
 *
 * Every peak ap_hmf_run reports must be BIT-IDENTICAL to ap_mf_run's for the
 * same pair and bin - not close, identical - because when the gate fires the
 * hierarchical path runs the ordinary filter.  The only permitted difference is
 * omission, and only at the calibrated rate.  A test that allowed a tolerance
 * here would pass even if the refinement path silently diverged.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "apogee.h"

static unsigned long rs=88172645463325252ULL;
static double urand(void){ rs^=rs<<13; rs^=rs>>7; rs^=rs<<17; return (rs>>11)*(1.0/9007199254740992.0); }
static double nrand(void){
  double u=urand(), v=urand();
  if(u<1e-300) u=1e-300;
  return sqrt(-2*log(u))*cos(2*M_PI*v);
}

static int fails=0, checks=0;


/* Build a template with a stated fraction of its SNR below n/8.
 *
 * The band edge is fixed in Hz, not in bins: at a 2048 Hz sample rate, 256 Hz
 * lands at bin 256*n/2048 = n/8 for any n.  So the reference band is n/8 at
 * every size, and growing n analyses more time rather than more bandwidth.
 *
 * `want` is a POWER fraction (0.85 power is 0.92 SNR -- the two are easy to
 * conflate and differ substantially).  Using
 * a fixed power-law exponent instead makes the template far more concentrated
 * as n grows -- f^-0.9 puts 99% of its power below n/8 at 2^20 -- which flatters
 * every hierarchical measurement into meaninglessness.
 */
static void make_template_pow(float *H,size_t n,double want){
  const size_t mref=n/8;
  double lo=-8.0,hi=4.0;
  for(int it=0;it<200;it++){
    double s=0.5*(lo+hi), tot=0, low=0;
    for(size_t f=1;f<n/2;f++){ double p=pow((double)f,2*s); tot+=p; if(f<mref) low+=p; }
    if(low/tot<want) hi=s; else lo=s;
  }
  const double s=0.5*(lo+hi);
  double e=0;
  for(size_t k=0;k<2*n;k++) H[k]=0.f;
  for(size_t f=1;f<n/2;f++){ double a=pow((double)f,s); H[2*f]=(float)a; e+=a*a; }
  e=sqrt(e);
  for(size_t f=1;f<n/2;f++) H[2*f]/=(float)e;
}


/* data = noise + amp * template shifted to `lag` */
static void make_data(float *D,const float *H,size_t n,double amp,size_t lag){
  for(size_t f=0;f<n;f++){
    double re=nrand(), im=nrand();
    double c=cos(-2*M_PI*(double)f*lag/(double)n), s=sin(-2*M_PI*(double)f*lag/(double)n);
    D[2*f]=(float)(re+amp*(H[2*f]*c-H[2*f+1]*s));
    D[2*f+1]=(float)(im+amp*(H[2*f]*s+H[2*f+1]*c));
  }
}

static void compare(const char *what,size_t n,int ND,int NT,
                    size_t binsize,float thr,size_t start,size_t end,
                    float snr,float fd,double amp,int *pmiss,int *ptot)
{
  float *H=malloc(2*n*sizeof(float)*NT), *D=malloc(2*n*sizeof(float)*ND);
  ap_mf_plan  *mf =ap_mf_create(n,ND,NT);
  ap_hmf_plan *hmf=ap_hmf_create(n,ND,NT,snr,fd);
  if(!mf||!hmf){ printf("  %-28s SKIP (no plan)\n",what); free(H);free(D); return; }
  for(int t=0;t<NT;t++) make_template_pow(H+(size_t)t*2*n,n,0.85-0.03*t);
  for(int d=0;d<ND;d++) make_data(D+(size_t)d*2*n,H,n,amp,(size_t)(start+ (end-start)/3 + 7*d));
  for(int d=0;d<ND;d++){ ap_mf_set_data(mf,d,D+(size_t)d*2*n); ap_hmf_set_data(hmf,d,D+(size_t)d*2*n); }
  for(int t=0;t<NT;t++){ ap_mf_set_template(mf,t,H+(size_t)t*2*n); ap_hmf_set_template(hmf,t,H+(size_t)t*2*n); }

  size_t nb=ap_mf_nbins(mf,binsize,start,end);
  ap_peak *pa=calloc((size_t)ND*NT*nb,sizeof(ap_peak));
  ap_peak *pb=calloc((size_t)ND*NT*nb,sizeof(ap_peak));
  int *ca=calloc((size_t)ND*NT,sizeof(int)), *cb=calloc((size_t)ND*NT,sizeof(int));
  ap_mf_run (mf ,0,ND,0,NT,binsize,thr,pa,ca,start,end);
  ap_hmf_run(hmf,0,ND,0,NT,binsize,thr,pb,cb,start,end);

  int extra=0,differ=0,miss=0,tot=0;
  for(size_t i=0;i<(size_t)ND*NT*nb;i++){
    checks++;
    if(pa[i].index>=0) tot++;
    if(pb[i].index>=0 && pa[i].index<0){ extra++; continue; }         /* invented */
    if(pb[i].index<0 && pa[i].index>=0){ miss++; continue; }          /* allowed  */
    if(pb[i].index>=0){
      if(pa[i].index!=pb[i].index ||
         memcmp(&pa[i].re,&pb[i].re,sizeof(float)) ||
         memcmp(&pa[i].im,&pb[i].im,sizeof(float)) ||
         memcmp(&pa[i].magnitude,&pb[i].magnitude,sizeof(float))) differ++;
    }
  }
  long pr,tg; ap_hmf_stats(hmf,&pr,&tg);
  int bad = extra||differ;
  printf("  %-28s %s  peaks=%d missed=%d trig=%ld/%ld%s%s\n",what,
         bad?"FAIL":"ok  ",tot,miss,tg,pr,
         extra?"  INVENTED PEAK":"", differ?"  VALUE DIFFERS":"");
  if(bad) fails++;
  if(pmiss) *pmiss+=miss;
  if(ptot)  *ptot +=tot;
  free(pa);free(pb);free(ca);free(cb);free(H);free(D);
  ap_mf_destroy(mf); ap_hmf_destroy(hmf);
}

int main(void){
  printf("hierarchical matched filter (backend %s)\n",ap_isa());

  printf("\n bit-identity and no invented peaks\n");
  int miss=0,tot=0;
  compare("2^12 16x16 loud",      4096,16,16,1024, 8.f,   0,4096,5.5f,1e-2f,60.0,&miss,&tot);
  compare("2^12 16x16 marginal",  4096,16,16,1024, 4.f,   0,4096,5.5f,1e-2f,12.0,&miss,&tot);
  compare("2^12 window subset",   4096, 8, 8, 512, 4.f, 512,3584,5.5f,1e-3f,12.0,&miss,&tot);
  compare("2^12 ragged bins",     4096, 4, 4, 700, 4.f, 300,3900,5.5f,1e-2f,12.0,&miss,&tot);
  compare("2^13 8x8",             8192, 8, 8,1024, 4.f,   0,8192,6.0f,1e-2f,12.0,&miss,&tot);
  compare("2^12 1x1",             4096, 1, 1,4096, 4.f,   0,4096,5.0f,1e-2f,12.0,&miss,&tot);
  compare("2^12 3x5",             4096, 3, 5, 256, 4.f,   0,4096,5.5f,1e-4f,12.0,&miss,&tot);
  compare("2^12 pure noise",      4096, 8, 8,1024,20.f,   0,4096,5.5f,1e-2f, 0.0,&miss,&tot);
  /* The design table covers 2^10..2^20.  Large N picks a very small band
     relative to n, which is where a mis-scaled gate would show up as either a
     flood of triggers or silent omissions -- so cover both ends. */
  compare("2^10 small",           1024, 4, 4, 256, 4.f,   0,1024,5.5f,1e-2f,12.0,&miss,&tot);
  compare("2^16 8x8",            65536, 4, 4,4096, 4.f,   0,65536,5.5f,1e-2f,12.0,&miss,&tot);
  compare("2^18 2x2",           262144, 2, 2,8192, 4.f,   0,262144,5.5f,1e-2f,12.0,&miss,&tot);
  compare("2^20 1x1",          1048576, 1, 1,8192, 4.f,   0,1048576,5.5f,1e-2f,12.0,&miss,&tot);
  compare("2^20 noise",        1048576, 2, 2,8192,20.f,   0,1048576,5.5f,1e-2f, 0.0,&miss,&tot);

  /* blocking invariance: a sub-block must equal the matching slice, including
     which pairs were gated away */
  printf("\n blocking invariance\n");
  {
    const size_t n=4096; const int ND=8,NT=8;
    float *H=malloc(2*n*sizeof(float)*NT), *D=malloc(2*n*sizeof(float)*ND);
    for(int t=0;t<NT;t++) make_template_pow(H+(size_t)t*2*n,n,0.85);
    for(int d=0;d<ND;d++) make_data(D+(size_t)d*2*n,H,n,12.0,600+13*d);
    ap_hmf_plan *h=ap_hmf_create(n,ND,NT,5.5f,1e-2f);
    for(int d=0;d<ND;d++) ap_hmf_set_data(h,d,D+(size_t)d*2*n);
    for(int t=0;t<NT;t++) ap_hmf_set_template(h,t,H+(size_t)t*2*n);
    size_t nb=ap_hmf_nbins(h,512,0,n);
    ap_peak *all=calloc((size_t)ND*NT*nb,sizeof(ap_peak));
    ap_peak *sub=calloc((size_t)2*3*nb,sizeof(ap_peak));
    ap_hmf_run(h,0,ND,0,NT,512,4.f,all,NULL,0,n);
    ap_hmf_run(h,2,2,3,3,512,4.f,sub,NULL,0,n);
    int bad=0;
    for(int d=0;d<2;d++) for(int t=0;t<3;t++) for(size_t b=0;b<nb;b++){
      ap_peak *x=&all[(size_t)((d+2)*NT+(t+3))*nb+b], *y=&sub[(size_t)(d*3+t)*nb+b];
      checks++;
      if(x->index!=y->index||memcmp(&x->magnitude,&y->magnitude,sizeof(float))) bad++;
    }
    printf("  %-28s %s  (%d mismatches)\n","sub-block equals slice",bad?"FAIL":"ok  ",bad);
    if(bad) fails++;
    free(all);free(sub);free(H);free(D); ap_hmf_destroy(h);
  }

  printf("\n omissions: %d of %d peaks (%.2f%%)\n",miss,tot,tot?100.0*miss/tot:0.0);
  printf("\n%d checks, %d failures\n",checks,fails);
  return fails?1:0;
}
