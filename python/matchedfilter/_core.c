/* matchedfilter Python extension: the matched filter.
 *
 * The whole D x T pair loop happens in one call into C, so no per-pair Python
 * overhead reaches the measurement.  Only the matched filter is exposed: there is
 * no transform plan to hand out, because callers bring their own spectra. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdlib.h>
#include <stdint.h>
#include <limits.h>
#include "matchedfilter.h"
#include "transform.h"

/* Validate the extension boundary independently of the Python convenience API.
   Divide byte capacities instead of multiplying untrusted sizes. */
static int output_shape(Py_ssize_t rows,size_t nb,Py_buffer *ix,Py_buffer *val,
                        Py_buffer *mag,Py_buffer *cnt,Py_ssize_t *need){
  if(rows<1 || nb<1 || nb>(size_t)PY_SSIZE_T_MAX/(size_t)rows){
    PyErr_SetString(PyExc_ValueError,"invalid or overflowing output shape"); return 0;
  }
  *need=rows*(Py_ssize_t)nb;
  if(*need>PY_SSIZE_T_MAX/(Py_ssize_t)sizeof(ap_peak)
     || ix->len/8<*need || val->len/8<*need
     || (mag->len && mag->len/4<*need) || cnt->len/4<rows){
    PyErr_SetString(PyExc_ValueError,"output arrays too small or output shape overflows"); return 0;
  }
  return 1;
}
static int run_shape(Py_ssize_t n,int maxd,int maxt,int d0,int nd,int t0,int nt,
                     Py_ssize_t bs,Py_ssize_t start,Py_ssize_t end,
                     size_t *nb,Py_ssize_t *rows){
  if(d0<0 || nd<1 || nd>maxd || d0>maxd-nd || t0<0 || nt<1
     || nt>maxt || t0>maxt-nt || bs<1 || start<0 || end<=start || start>=n){
    PyErr_SetString(PyExc_ValueError,"invalid subrange, binsize or window"); return 0;
  }
  if(end>n) end=n;
  *nb=1+(size_t)(end-start-1)/(size_t)bs;
  if((Py_ssize_t)nd>PY_SSIZE_T_MAX/nt){
    PyErr_SetString(PyExc_ValueError,"pair count overflows"); return 0;
  }
  *rows=(Py_ssize_t)nd*nt;
  return 1;
}
static int series_shape(Py_ssize_t n,int maxt,int t0,int nt,Py_ssize_t binsize,
                        Py_buffer *ser,Py_buffer *st,Py_buffer *ws,Py_buffer *we,
                        int *blocks,size_t *nb,Py_ssize_t *rows){
  const Py_ssize_t unit=(Py_ssize_t)sizeof(size_t);
  if(ser->len%8 || st->len<unit || st->len%unit || st->len/unit>INT_MAX
     || ws->len!=st->len || we->len!=st->len){
    PyErr_SetString(PyExc_ValueError,"invalid series or block-layout buffer lengths"); return 0;
  }
  *blocks=(int)(st->len/unit);
  const size_t *starts=st->buf,*lo=ws->buf,*hi=we->buf;
  size_t first=0;
  for(int i=0;i<*blocks;i++){
    if(starts[i]>SIZE_MAX-(size_t)n || lo[i]>(size_t)PY_SSIZE_T_MAX
       || hi[i]>(size_t)PY_SSIZE_T_MAX){
      PyErr_SetString(PyExc_ValueError,"block offset or window overflows"); return 0;
    }
    Py_ssize_t ignored;
    size_t bins;
    if(!run_shape(n,1,maxt,0,1,t0,nt,binsize,(Py_ssize_t)lo[i],
                  (Py_ssize_t)hi[i],&bins,&ignored)) return 0;
    if(i && bins!=first){
      PyErr_SetString(PyExc_ValueError,"block windows must have equal bin counts"); return 0;
    }
    first=bins;
  }
  if((Py_ssize_t)*blocks>PY_SSIZE_T_MAX/nt){
    PyErr_SetString(PyExc_ValueError,"pair count overflows"); return 0;
  }
  *nb=first; *rows=(Py_ssize_t)*blocks*nt; return 1;
}
static ap_peak *reserve_peaks(ap_peak **storage,Py_ssize_t *capacity,Py_ssize_t need){
  if(need>*capacity){
    ap_peak *next=PyMem_Realloc(*storage,(size_t)need*sizeof(ap_peak));
    if(!next){ PyErr_NoMemory(); return NULL; }
    *storage=next; *capacity=need;
  }
  return *storage;
}

/* ---------------- matched filter ---------------- */
typedef struct { PyObject_HEAD ap_mf_plan *p; Py_ssize_t n; int nd,nt; ap_peak *peaks; Py_ssize_t peak_capacity; } MFObject;

static int MF_init(MFObject *self,PyObject *args,PyObject *kw){
  Py_ssize_t n; int nd,nt; (void)kw;
  if(!PyArg_ParseTuple(args,"nii",&n,&nd,&nt)) return -1;
  self->p=ap_mf_create((size_t)n,nd,nt);
  if(!self->p){ PyErr_Format(PyExc_ValueError,
      "unsupported matched-filter shape n=%zd ndata=%d ntemplates=%d",n,nd,nt); return -1; }
  self->n=n; self->nd=nd; self->nt=nt; return 0;
}
static void MF_dealloc(MFObject *self){
  if(self->p) ap_mf_destroy(self->p);
  PyMem_Free(self->peaks);
  Py_TYPE(self)->tp_free((PyObject*)self);
}
static PyObject *MF_set(MFObject *self,PyObject *args,int is_data){
  int i; Py_buffer b;
  if(!PyArg_ParseTuple(args,"iy*",&i,&b)) return NULL;
  if(b.len < self->n*2*(Py_ssize_t)sizeof(float)){
    PyBuffer_Release(&b);
    return PyErr_Format(PyExc_ValueError,"segment must hold %zd complex64 samples",self->n);
  }
  int r;
  Py_BEGIN_ALLOW_THREADS
  r = is_data ? ap_mf_set_data(self->p,i,(const float*)b.buf)
              : ap_mf_set_template(self->p,i,(const float*)b.buf);
  Py_END_ALLOW_THREADS
  PyBuffer_Release(&b);
  if(r<0) return PyErr_Format(PyExc_IndexError,"index %d out of range",i);
  Py_RETURN_NONE;
}
static PyObject *MF_set_data(MFObject *s,PyObject *a){ return MF_set(s,a,1); }
static PyObject *MF_set_template(MFObject *s,PyObject *a){ return MF_set(s,a,0); }

/* run(d0,nd,t0,nt,binsize,threshold,start,end, idx,val,mag,counts) -> total */
static PyObject *MF_run(MFObject *self,PyObject *args){
  int d0,nd,t0,nt; Py_ssize_t binsize,start,end; double thr;
  Py_buffer bidx,bval,bmag,bcnt;
  if(!PyArg_ParseTuple(args,"iiiindnnw*w*w*w*",&d0,&nd,&t0,&nt,&binsize,&thr,
                       &start,&end,&bidx,&bval,&bmag,&bcnt)) return NULL;
  size_t nb; Py_ssize_t rows,need;
  if(!run_shape(self->n,self->nd,self->nt,d0,nd,t0,nt,binsize,start,end,&nb,&rows)
     || !output_shape(rows,nb,&bidx,&bval,&bmag,&bcnt,&need)){
    PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
    PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return NULL;
  }
  ap_peak *pk=reserve_peaks(&self->peaks,&self->peak_capacity,need);
  if(!pk){ PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
           PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return NULL; }
  int tot;
  Py_BEGIN_ALLOW_THREADS
  tot=ap_mf_run(self->p,d0,nd,t0,nt,(size_t)binsize,(float)thr,pk,(int*)bcnt.buf,
                (size_t)start,(size_t)end);
  Py_END_ALLOW_THREADS
  if(tot>=0){
    long long *ix=(long long*)bidx.buf; float *vl=(float*)bval.buf,*mg=bmag.len ? (float*)bmag.buf : NULL;
    for(Py_ssize_t a=0;a<need;a++){
      ix[a]=(long long)pk[a].index; vl[2*a]=pk[a].re; vl[2*a+1]=pk[a].im; if(mg) mg[a]=pk[a].magnitude;
    }
  }
  PyBuffer_Release(&bidx);PyBuffer_Release(&bval);PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt);
  if(tot<0){ PyErr_SetString(PyExc_RuntimeError,"matchedfilter: matched filter failed"); return NULL; }
  return PyLong_FromLong(tot);
}
/* run_series(series, starts, wstart, wend, t0, nt, binsize, thr, idx,val,mag,cnt) */
static PyObject *MF_run_series(MFObject *self,PyObject *args){
  Py_buffer bs,bst,bws,bwe,bidx,bval,bmag,bcnt;
  int t0,nt; Py_ssize_t binsize; double thr;
  if(!PyArg_ParseTuple(args,"y*y*y*y*iindw*w*w*w*",&bs,&bst,&bws,&bwe,
                       &t0,&nt,&binsize,&thr,&bidx,&bval,&bmag,&bcnt)) return NULL;
  int nblocks; size_t nb;
  Py_ssize_t rows,need;
  if(!series_shape(self->n,self->nt,t0,nt,binsize,&bs,&bst,&bws,&bwe,
                   &nblocks,&nb,&rows)
     || !output_shape(rows,nb,&bidx,&bval,&bmag,&bcnt,&need)){
    PyBuffer_Release(&bs);PyBuffer_Release(&bst);PyBuffer_Release(&bws);
    PyBuffer_Release(&bwe);PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
    PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return NULL;
  }
  size_t nseries=(size_t)(bs.len/8);
  ap_peak *pk=reserve_peaks(&self->peaks,&self->peak_capacity,need);
  if(!pk){ PyBuffer_Release(&bs);PyBuffer_Release(&bst);PyBuffer_Release(&bws);
           PyBuffer_Release(&bwe);PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
           PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return NULL; }
  int tot;
  Py_BEGIN_ALLOW_THREADS
  tot=ap_mf_run_series(self->p,(const float*)bs.buf,nseries,
                       (const size_t*)bst.buf,(const size_t*)bws.buf,
                       (const size_t*)bwe.buf,nblocks,t0,nt,(size_t)binsize,
                       (float)thr,pk,(int*)bcnt.buf);
  Py_END_ALLOW_THREADS
  if(tot>=0){
    long long *ix=(long long*)bidx.buf; float *vl=(float*)bval.buf,*mg=bmag.len ? (float*)bmag.buf : NULL;
    for(Py_ssize_t a=0;a<need;a++){
      ix[a]=(long long)pk[a].index; vl[2*a]=pk[a].re; vl[2*a+1]=pk[a].im; if(mg) mg[a]=pk[a].magnitude;
    }
  }
  PyBuffer_Release(&bs);PyBuffer_Release(&bst);PyBuffer_Release(&bws);
  PyBuffer_Release(&bwe);PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
  PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt);
  if(tot<0){ PyErr_SetString(PyExc_RuntimeError,"matchedfilter: run_series failed"); return NULL; }
  return PyLong_FromLong(tot);
}
static PyObject *MF_nbins(MFObject *self,PyObject *args){
  Py_ssize_t bs,st,en;
  if(!PyArg_ParseTuple(args,"nnn",&bs,&st,&en)) return NULL;
  return PyLong_FromSize_t(ap_mf_nbins(self->p,(size_t)bs,(size_t)st,(size_t)en));
}
static PyMethodDef MF_methods[]={
  {"set_data",(PyCFunction)MF_set_data,METH_VARARGS,"set_data(i, buffer)"},
  {"set_template",(PyCFunction)MF_set_template,METH_VARARGS,"set_template(i, buffer)"},
  {"run",(PyCFunction)MF_run,METH_VARARGS,"run(...) -> total crossings"},
  {"run_series",(PyCFunction)MF_run_series,METH_VARARGS,"run_series(...)"},
  {"nbins",(PyCFunction)MF_nbins,METH_VARARGS,"nbins(binsize, start, end)"},
  {NULL}
};
static PyTypeObject MFType={
  PyVarObject_HEAD_INIT(NULL,0)
  .tp_name="matchedfilter._core.MF", .tp_basicsize=sizeof(MFObject),
  .tp_flags=Py_TPFLAGS_DEFAULT, .tp_new=PyType_GenericNew,
  .tp_init=(initproc)MF_init, .tp_dealloc=(destructor)MF_dealloc,
  .tp_methods=MF_methods, .tp_doc="matchedfilter matched filter (opaque)",
};

/* ---------------- hierarchical matched filter ---------------- */
/* Same shape as MF, so the Python class can share almost all of its code.  The
   only genuinely new surface is stats(), which reports the trigger rate - the
   quantity the whole speedup rides on, and the first thing to look at when the
   filter is slower than expected on a particular data set. */
typedef struct { PyObject_HEAD ap_hmf_plan *p; Py_ssize_t n; int nd,nt; ap_peak *peaks; Py_ssize_t peak_capacity; } HMFObject;

static int HMF_init(HMFObject *self,PyObject *args,PyObject *kw){
  Py_ssize_t n; int nd,nt; double snr,fd; (void)kw;
  Py_ssize_t band=0; int u=0,k=0;
  if(!PyArg_ParseTuple(args,"niidd|nii",&n,&nd,&nt,&snr,&fd,&band,&u,&k)) return -1;
  /* band and taps are required: the choice belongs to the measured tuning
     tables, which the Python class reads and which refuse rather than guess
     outside their coverage. `u` is accepted and ignored -- the oversample is
     gone and the argument is kept only so old callers still load. */
  (void)u;
  if(!band){ PyErr_SetString(PyExc_ValueError,
      "band and taps are required; HierarchicalFilter picks them "
      "from the tuning tables"); return -1; }
  self->p = ap_hmf_create_ex((size_t)n,nd,nt,(float)snr,(float)fd,(size_t)band,k);
  if(!self->p){ PyErr_Format(PyExc_ValueError,
      "no hierarchical plan for n=%zd band=%zd u=%d k=%d",n,band,u,k); return -1; }
  self->n=n; self->nd=nd; self->nt=nt; return 0;
}
static void HMF_dealloc(HMFObject *self){
  if(self->p) ap_hmf_destroy(self->p);
  PyMem_Free(self->peaks);
  Py_TYPE(self)->tp_free((PyObject*)self);
}
static PyObject *HMF_set(HMFObject *self,PyObject *args,int is_data){
  int i; Py_buffer b;
  if(!PyArg_ParseTuple(args,"iy*",&i,&b)) return NULL;
  if(b.len < self->n*2*(Py_ssize_t)sizeof(float)){
    PyBuffer_Release(&b);
    return PyErr_Format(PyExc_ValueError,"segment must hold %zd complex64 samples",self->n);
  }
  int r;
  Py_BEGIN_ALLOW_THREADS
  r = is_data ? ap_hmf_set_data(self->p,i,(const float*)b.buf)
              : ap_hmf_set_template(self->p,i,(const float*)b.buf);
  Py_END_ALLOW_THREADS
  PyBuffer_Release(&b);
  if(r<0) return PyErr_Format(PyExc_IndexError,"index %d out of range",i);
  Py_RETURN_NONE;
}
static PyObject *HMF_set_reference(HMFObject *self,PyObject *args){
  Py_buffer b;
  if(!PyArg_ParseTuple(args,"z*",&b)) return NULL;
  int r;
  if(!b.buf){ r=ap_hmf_set_reference(self->p,NULL); }
  else {
    if(b.len < self->n*(Py_ssize_t)sizeof(float)){
      PyBuffer_Release(&b);
      return PyErr_Format(PyExc_ValueError,
                          "reference must hold %zd float32 values",self->n);
    }
    r=ap_hmf_set_reference(self->p,(const float*)b.buf);
  }
  PyBuffer_Release(&b);
  if(r<0){ PyErr_SetString(PyExc_ValueError,"matchedfilter: bad reference"); return NULL; }
  Py_RETURN_NONE;
}
static PyObject *HMF_set_data(HMFObject *s,PyObject *a){ return HMF_set(s,a,1); }
static PyObject *HMF_set_template(HMFObject *s,PyObject *a){ return HMF_set(s,a,0); }

static PyObject *HMF_run(HMFObject *self,PyObject *args){
  int d0,nd,t0,nt; Py_ssize_t binsize,start,end; double thr;
  Py_buffer bidx,bval,bmag,bcnt;
  if(!PyArg_ParseTuple(args,"iiiindnnw*w*w*w*",&d0,&nd,&t0,&nt,&binsize,&thr,
                       &start,&end,&bidx,&bval,&bmag,&bcnt)) return NULL;
  size_t nb; Py_ssize_t rows,need;
  if(!run_shape(self->n,self->nd,self->nt,d0,nd,t0,nt,binsize,start,end,&nb,&rows)
     || !output_shape(rows,nb,&bidx,&bval,&bmag,&bcnt,&need)){
    PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
    PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return NULL;
  }
  ap_peak *pk=reserve_peaks(&self->peaks,&self->peak_capacity,need);
  if(!pk){ PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
           PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return NULL; }
  int tot;
  Py_BEGIN_ALLOW_THREADS
  tot=ap_hmf_run(self->p,d0,nd,t0,nt,(size_t)binsize,(float)thr,pk,(int*)bcnt.buf,
                 (size_t)start,(size_t)end);
  Py_END_ALLOW_THREADS
  if(tot>=0){
    long long *ix=(long long*)bidx.buf; float *vl=(float*)bval.buf,*mg=bmag.len ? (float*)bmag.buf : NULL;
    for(Py_ssize_t a=0;a<need;a++){
      ix[a]=(long long)pk[a].index; vl[2*a]=pk[a].re; vl[2*a+1]=pk[a].im; if(mg) mg[a]=pk[a].magnitude;
    }
  }
  PyBuffer_Release(&bidx);PyBuffer_Release(&bval);PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt);
  if(tot<0){ PyErr_SetString(PyExc_RuntimeError,"matchedfilter: hierarchical filter failed"); return NULL; }
  return PyLong_FromLong(tot);
}
/* run_series(series, starts, wstart, wend, t0, nt, binsize, thr, idx,val,mag,cnt) */
static PyObject *HMF_run_series(HMFObject *self,PyObject *args){
  Py_buffer bs,bst,bws,bwe,bidx,bval,bmag,bcnt;
  int t0,nt; Py_ssize_t binsize; double thr;
  if(!PyArg_ParseTuple(args,"y*y*y*y*iindw*w*w*w*",&bs,&bst,&bws,&bwe,
                       &t0,&nt,&binsize,&thr,&bidx,&bval,&bmag,&bcnt)) return NULL;
  int nblocks; size_t nb;
  Py_ssize_t rows,need;
  if(!series_shape(self->n,self->nt,t0,nt,binsize,&bs,&bst,&bws,&bwe,
                   &nblocks,&nb,&rows)
     || !output_shape(rows,nb,&bidx,&bval,&bmag,&bcnt,&need)){
    PyBuffer_Release(&bs);PyBuffer_Release(&bst);PyBuffer_Release(&bws);
    PyBuffer_Release(&bwe);PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
    PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return NULL;
  }
  size_t nseries=(size_t)(bs.len/8);
  ap_peak *pk=reserve_peaks(&self->peaks,&self->peak_capacity,need);
  if(!pk){ PyBuffer_Release(&bs);PyBuffer_Release(&bst);PyBuffer_Release(&bws);
           PyBuffer_Release(&bwe);PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
           PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return NULL; }
  int tot;
  Py_BEGIN_ALLOW_THREADS
  tot=ap_hmf_run_series(self->p,(const float*)bs.buf,nseries,
                        (const size_t*)bst.buf,(const size_t*)bws.buf,
                        (const size_t*)bwe.buf,nblocks,t0,nt,(size_t)binsize,
                        (float)thr,pk,(int*)bcnt.buf);
  Py_END_ALLOW_THREADS
  if(tot>=0){
    long long *ix=(long long*)bidx.buf; float *vl=(float*)bval.buf,*mg=bmag.len ? (float*)bmag.buf : NULL;
    for(Py_ssize_t a=0;a<need;a++){
      ix[a]=(long long)pk[a].index; vl[2*a]=pk[a].re; vl[2*a+1]=pk[a].im; if(mg) mg[a]=pk[a].magnitude;
    }
  }
  PyBuffer_Release(&bs);PyBuffer_Release(&bst);PyBuffer_Release(&bws);
  PyBuffer_Release(&bwe);PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
  PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt);
  if(tot<0){ PyErr_SetString(PyExc_RuntimeError,"matchedfilter: run_series failed"); return NULL; }
  return PyLong_FromLong(tot);
}
static PyObject *HMF_nbins(HMFObject *self,PyObject *args){
  Py_ssize_t bs,st,en;
  if(!PyArg_ParseTuple(args,"nnn",&bs,&st,&en)) return NULL;
  return PyLong_FromSize_t(ap_hmf_nbins(self->p,(size_t)bs,(size_t)st,(size_t)en));
}
static PyObject *HMF_stats(HMFObject *self,PyObject *a){
  long pr=0,tg=0; (void)a; ap_hmf_stats(self->p,&pr,&tg);
  return Py_BuildValue("(ll)",pr,tg);
}
static PyObject *HMF_coarse_threshold(HMFObject *self,PyObject *args){
  float thr,out=0;
  if(!PyArg_ParseTuple(args,"f",&thr)) return NULL;
  if(ap_hmf_coarse_thresholds(self->p,thr,&out)<0){
    PyErr_SetString(PyExc_RuntimeError,"coarse_threshold failed"); return NULL; }
  return PyFloat_FromDouble((double)out);
}
static PyObject *HMF_config(HMFObject *self,PyObject *a){
  size_t band=0; int k=0; (void)a; ap_hmf_config(self->p,&band,&k);
  /* Three values still, so the Python side is unchanged; the middle one is
     a constant 1 where the oversample used to be. */
  return Py_BuildValue("(nii)",(Py_ssize_t)band,1,k);
}
static PyObject *HMF_set_threshold(HMFObject *self,PyObject *args){
  double t; if(!PyArg_ParseTuple(args,"d",&t)) return NULL;
  if(ap_hmf_set_threshold(self->p,(float)t)<0){
    PyErr_SetString(PyExc_RuntimeError,"set_threshold failed"); return NULL; }
  Py_RETURN_NONE;
}
static PyObject *HMF_set_first_stage(HMFObject *self,PyObject *args){
  float snr;
  if(!PyArg_ParseTuple(args,"f",&snr)) return NULL;
  if(ap_hmf_set_first_stage(self->p,snr)<0){
    PyErr_SetString(PyExc_RuntimeError,"set_first_stage failed"); return NULL; }
  Py_RETURN_NONE;
}

static PyMethodDef HMF_methods[]={
  {"set_data",(PyCFunction)HMF_set_data,METH_VARARGS,"set_data(i, buffer)"},
  {"set_template",(PyCFunction)HMF_set_template,METH_VARARGS,"set_template(i, buffer)"},
  {"set_reference",(PyCFunction)HMF_set_reference,METH_VARARGS,"set_reference(buffer|None)"},
  {"set_first_stage",(PyCFunction)HMF_set_first_stage,METH_VARARGS,"set_first_stage(snr)"},
  {"set_threshold",(PyCFunction)HMF_set_threshold,METH_VARARGS,"set_threshold(t)"},
  {"run",(PyCFunction)HMF_run,METH_VARARGS,"run(...) -> total crossings"},
  {"nbins",(PyCFunction)HMF_nbins,METH_VARARGS,"nbins(binsize, start, end)"},
  {"run_series",(PyCFunction)HMF_run_series,METH_VARARGS,"run_series(...)"},
  {"stats",(PyCFunction)HMF_stats,METH_NOARGS,"stats() -> (pairs, triggers)"},
  {"config",(PyCFunction)HMF_config,METH_NOARGS,"config() -> (band, 1, taps)"},
  {"coarse_threshold",(PyCFunction)HMF_coarse_threshold,METH_VARARGS,NULL},
  {NULL}
};
static PyTypeObject HMFType={
  PyVarObject_HEAD_INIT(NULL,0)
  .tp_name="matchedfilter._core.HMF", .tp_basicsize=sizeof(HMFObject),
  .tp_flags=Py_TPFLAGS_DEFAULT, .tp_new=PyType_GenericNew,
  .tp_init=(initproc)HMF_init, .tp_dealloc=(destructor)HMF_dealloc,
  .tp_methods=HMF_methods, .tp_doc="matchedfilter hierarchical matched filter (opaque)",
};

static PyObject *M_backend(PyObject *self,PyObject *args){
  (void)self;(void)args;
  return PyUnicode_FromString(ap_isa());
}
static PyObject *M_targets(PyObject *self,PyObject *args){
  (void)self;(void)args;
  int n=ap_target_count();
  PyObject *t=PyTuple_New(n);
  if(!t) return NULL;
  for(int i=0;i<n;i++){
    PyObject *s=PyUnicode_FromString(ap_target_name(i));
    if(!s){ Py_DECREF(t); return NULL; }
    PyTuple_SET_ITEM(t,i,s);
  }
  return t;
}
static PyObject *M_set_target(PyObject *self,PyObject *args){
  (void)self;
  const char *name=NULL;
  if(!PyArg_ParseTuple(args,"z",&name)) return NULL;
  if(ap_set_target(name)){
    PyErr_Format(PyExc_ValueError,"no such target in this build: %s",name);
    return NULL;
  }
  Py_RETURN_NONE;
}
static PyMethodDef methods[]={
  {"backend",M_backend,METH_NOARGS,"backend() -> name of the selected kernel"},
  {"targets",M_targets,METH_NOARGS,"targets() -> names this build can run here"},
  {"set_target",M_set_target,METH_VARARGS,"set_target(name|None) -> narrow the choice"},
  {NULL,NULL,0,NULL}};
static struct PyModuleDef mod={PyModuleDef_HEAD_INIT,"matchedfilter._core",NULL,-1,methods};
PyMODINIT_FUNC PyInit__core(void){
  if(PyType_Ready(&MFType)<0) return NULL;
  if(PyType_Ready(&HMFType)<0) return NULL;
  PyObject *m=PyModule_Create(&mod);
  if(!m) return NULL;
  Py_INCREF(&MFType);   PyModule_AddObject(m,"MF",(PyObject*)&MFType);
  Py_INCREF(&HMFType);  PyModule_AddObject(m,"HMF",(PyObject*)&HMFType);
  return m;
}
