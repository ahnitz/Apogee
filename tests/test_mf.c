/* Batched matched filter, against an independent double-precision reference.
 * Plan in docs/matched-filter-plan.md; this implements its correctness section. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "peakfft.h"

static int checks=0, fails=0;
#define CK(c,...) do{ checks++; if(!(c)){ fails++; if(fails<25){printf("  FAIL ");printf(__VA_ARGS__);printf("\n");} } }while(0)

static unsigned long long rs=88172645463325252ULL;
static double u(void){ rs^=rs<<13; rs^=rs>>7; rs^=rs<<17; return (double)(rs>>11)/9007199254740992.0; }
static double gs(void){ return sqrt(-2.0*log(u()+1e-300))*cos(2*M_PI*u()); }

/* plain double radix-2 FFT, independent of everything under test */
static void dfft(double *re,double *im,size_t n,int sign){
  for(size_t i=1,j=0;i<n;i++){
    size_t b=n>>1; for(;j&b;b>>=1) j^=b; j^=b;
    if(i<j){ double t=re[i];re[i]=re[j];re[j]=t; t=im[i];im[i]=im[j];im[j]=t; }
  }
  for(size_t l=2;l<=n;l<<=1){
    double ang=sign*2.0*M_PI/(double)l;
    double wr=cos(ang), wi=sin(ang);
    for(size_t i=0;i<n;i+=l){
      double cr=1,ci=0;
      for(size_t k=0;k<l/2;k++){
        double ur=re[i+k],ui=im[i+k];
        double vr=re[i+k+l/2]*cr-im[i+k+l/2]*ci, vi=re[i+k+l/2]*ci+im[i+k+l/2]*cr;
        re[i+k]=ur+vr; im[i+k]=ui+vi;
        re[i+k+l/2]=ur-vr; im[i+k+l/2]=ui-vi;
        double nr=cr*wr-ci*wi; ci=cr*wi+ci*wr; cr=nr;
      }
    }
  }
}
/* reference correlation magnitudes for one pair */
static void refpair(const float *d,const float *h,size_t n,double *mag,double *zr,double *zi){
  double *dr=malloc(n*8),*di=malloc(n*8),*hr=malloc(n*8),*hi=malloc(n*8);
  for(size_t k=0;k<n;k++){ dr[k]=d[2*k]; di[k]=d[2*k+1]; hr[k]=h[2*k]; hi[k]=h[2*k+1]; }
  dfft(dr,di,n,-1); dfft(hr,hi,n,-1);
  for(size_t k=0;k<n;k++){
    double ar=dr[k],ai=di[k],br=hr[k],bi=-hi[k];      /* conj(H) */
    dr[k]=ar*br-ai*bi; di[k]=ar*bi+ai*br;
  }
  dfft(dr,di,n,+1);                                    /* unnormalised inverse */
  for(size_t k=0;k<n;k++){ mag[k]=hypot(dr[k],di[k]); zr[k]=dr[k]; zi[k]=di[k]; }
  free(dr);free(di);free(hr);free(hi);
}

static void run(size_t n,int D,int T,size_t binsize,size_t ws,size_t we,int usethr){
  pf_mf_plan *p=pf_mf_create(n,D,T); if(!p) return;
  float *data=malloc((size_t)D*2*n*4), *tmpl=malloc((size_t)T*2*n*4);
  for(int d=0;d<D;d++) for(size_t k=0;k<n;k++){
    data[(size_t)d*2*n+2*k]=(float)gs(); data[(size_t)d*2*n+2*k+1]=(float)gs(); }
  for(int t=0;t<T;t++) for(size_t k=0;k<n;k++){
    tmpl[(size_t)t*2*n+2*k]=(float)gs(); tmpl[(size_t)t*2*n+2*k+1]=(float)gs(); }
  /* segments are supplied already transformed */
  pf_plan *fp=pf_create(n); float *sp=malloc(2*n*4);
  for(int d=0;d<D;d++){ pf_fft(fp,data+(size_t)d*2*n,sp,PF_FORWARD);
    CK(pf_mf_set_data(p,d,sp)==0,"set_data %d",d); }
  for(int t=0;t<T;t++){ pf_fft(fp,tmpl+(size_t)t*2*n,sp,PF_FORWARD);
    CK(pf_mf_set_template(p,t,sp)==0,"set_template %d",t); }

  size_t nb=pf_mf_nbins(p,binsize,ws,we);
  pf_peak *pk=malloc((size_t)D*T*nb*sizeof(pf_peak));
  int *cnt=malloc((size_t)D*T*sizeof(int));
  double *mag=malloc(n*8),*zr=malloc(n*8),*zi=malloc(n*8);

  float T0=0.f;
  if(usethr){
    refpair(data,tmpl,n,mag,zr,zi);
    double mx=0; for(size_t k=ws;k<we;k++) if(mag[k]>mx) mx=mag[k];
    T0=(float)(mx*0.5);                       /* roughly half the pair's peak */
  }
  int tot=pf_mf_run(p,0,D,0,T,binsize,T0,pk,cnt,ws,we);
  CK(tot>=0,"pf_mf_run n=%zu D=%d T=%d",n,D,T);

  double worst=0;
  for(int d=0;d<D;d++) for(int t=0;t<T;t++){
    refpair(data+(size_t)d*2*n,tmpl+(size_t)t*2*n,n,mag,zr,zi);
    size_t row=(size_t)d*T+t;
    double peak=0; for(size_t k=0;k<n;k++) if(mag[k]>peak) peak=mag[k];
    int c=0;
    for(size_t j=0;j<nb;j++){
      size_t lo=ws+j*binsize, hi=lo+binsize; if(hi>we) hi=we;
      size_t best=lo; for(size_t k=lo;k<hi;k++) if(mag[k]>mag[best]) best=k;
      pf_peak *q=&pk[row*nb+j];
      if(mag[best] <= (double)T0){
        CK(q->index==-1,"n=%zu d=%d t=%d bin %zu: expected empty, got %ld",n,d,t,j,q->index);
        continue;
      }
      c++;
      CK((size_t)q->index==best,"n=%zu d=%d t=%d bin %zu: index %ld, reference %zu",
         n,d,t,j,q->index,best);
      double rel=fabs(q->magnitude-mag[best])/peak;
      if(rel>worst) worst=rel;
      CK(rel<1e-5,"n=%zu d=%d t=%d bin %zu: magnitude rel err %.3e",n,d,t,j,rel);
    }
    CK(cnt[row]==c,"n=%zu d=%d t=%d: count %d expected %d",n,d,t,cnt[row],c);
  }
  /* blocking invariance: any sub-block equals the matching slice of the whole */
  if(D>1 && T>1){
    int nd=D/2, nt=T/2, d0=D-nd, t0=T-nt;
    pf_peak *sub=malloc((size_t)nd*nt*nb*sizeof(pf_peak));
    int *sc=malloc((size_t)nd*nt*sizeof(int));
    CK(pf_mf_run(p,d0,nd,t0,nt,binsize,T0,sub,sc,ws,we)>=0,"sub-block run");
    for(int d=0;d<nd;d++) for(int t=0;t<nt;t++){
      size_t rf=(size_t)(d0+d)*T+(t0+t), rs2=(size_t)d*nt+t;
      CK(sc[rs2]==cnt[rf],"sub-block count differs at d=%d t=%d",d0+d,t0+t);
      for(size_t j=0;j<nb;j++)
        CK(sub[rs2*nb+j].index==pk[rf*nb+j].index,
           "sub-block index differs at d=%d t=%d bin %zu",d0+d,t0+t,j);
    }
    free(sub);free(sc);
  }
  free(data);free(tmpl);free(pk);free(cnt);free(mag);free(zr);free(zi);free(sp);
  pf_destroy(fp); pf_mf_destroy(p);
}

/* template is a circular shift of the data: the peak must be exactly at that lag */
static void run_known(size_t n,int lag){
  pf_mf_plan *p=pf_mf_create(n,1,1); if(!p) return;
  float *d=malloc(2*n*4),*h=malloc(2*n*4);
  double energy=0;
  for(size_t k=0;k<n;k++){ d[2*k]=(float)gs(); d[2*k+1]=(float)gs();
    energy += (double)d[2*k]*d[2*k] + (double)d[2*k+1]*d[2*k+1]; }
  for(size_t k=0;k<n;k++){ size_t src=(k+(size_t)lag)%n;
    h[2*k]=d[2*src]; h[2*k+1]=d[2*src+1]; }
  { pf_plan *fp=pf_create(n); float *sp=malloc(2*n*4);
    pf_fft(fp,d,sp,PF_FORWARD); pf_mf_set_data(p,0,sp);
    pf_fft(fp,h,sp,PF_FORWARD); pf_mf_set_template(p,0,sp);
    free(sp); pf_destroy(fp); }

  pf_peak pk[1]; int c[1];
  pf_mf_run(p,0,1,0,1,n,0.f,pk,c,0,n);
  CK(pk[0].index==lag,"known-answer n=%zu: peak at %ld, expected lag %d",n,pk[0].index,lag);
  /* the backward transform is unnormalised, matching FFTW and MKL, so a perfect
     match returns n * energy rather than energy */
  double want = energy*(double)n;
  CK(fabs(pk[0].magnitude-want) <= 1e-4*want,
     "known-answer n=%zu: magnitude %g, expected n*energy %g",n,(double)pk[0].magnitude,want);
  free(d);free(h); pf_mf_destroy(p);
}

/* duplicating a template must give identical rows - catches state leaking */
static void run_reuse(size_t n){
  pf_mf_plan *p=pf_mf_create(n,2,3); if(!p) return;
  float *d=malloc(2*2*n*4),*h=malloc(3*2*n*4);
  for(size_t i=0;i<2*2*n;i++) d[i]=(float)gs();
  for(size_t i=0;i<3*2*n;i++) h[i]=(float)gs();
  memcpy(h+2*2*n, h, 2*n*sizeof(float));      /* template 2 == template 0 */
  { pf_plan *fp=pf_create(n); float *sp=malloc(2*n*4);
    for(int i=0;i<2;i++){ pf_fft(fp,d+(size_t)i*2*n,sp,PF_FORWARD); pf_mf_set_data(p,i,sp); }
    for(int i=0;i<3;i++){ pf_fft(fp,h+(size_t)i*2*n,sp,PF_FORWARD); pf_mf_set_template(p,i,sp); }
    free(sp); pf_destroy(fp); }
  size_t bs=n/4, nb=pf_mf_nbins(p,bs,0,n);
  pf_peak *pk=malloc(2*3*nb*sizeof(pf_peak)); int cnt[6];
  pf_mf_run(p,0,2,0,3,bs,0.f,pk,cnt,0,n);
  for(int dd=0;dd<2;dd++) for(size_t j=0;j<nb;j++){
    pf_peak *a=&pk[((size_t)dd*3+0)*nb+j], *b=&pk[((size_t)dd*3+2)*nb+j];
    CK(a->index==b->index && a->magnitude==b->magnitude,
       "reuse n=%zu d=%d bin %zu: duplicate template gave different results",n,dd,j);
  }
  free(d);free(h);free(pk); pf_mf_destroy(p);
}

int main(void){
  if(!pf_supported(1024)){ printf("test_mf: unsupported CPU, skipped\n"); return 0; }
  const int quick = getenv("PF_QUICK")!=NULL;
  run(1024,2,2,1024,0,1024,0);
  run(1024,2,2,256,0,1024,1);
  run_known(1024,137); run_known(4096,1000);
  run_reuse(1024);
  if(!quick){
    run(1024,16,16,1024,0,1024,0);          /* the 16x16 case from the brief */
    run(1024,16,16,256,200,700,1);          /* windowed + floor */
    run(1024,1,16,1024,0,1024,0);
    run(1024,16,1,1024,0,1024,0);
    run(1024,3,5,128,0,1024,1);
    run(1024,17,13,97,100,900,1);           /* non-power-of-two shapes, ragged bins */
    run(4096,4,4,1024,0,4096,0);
    run(4096,4,4,512,800,3000,1);
    run_known(1024,0); run_known(1024,1023);
    run_reuse(4096);
  }
  printf("test_mf %33s %d checks, %d failures  [%s]\n","",checks,fails,fails?"FAIL":"ok");
  return fails?1:0;
}
