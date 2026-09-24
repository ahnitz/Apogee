/* matchedfilter Python extension: the matched filter.
 *
 * The whole D x T pair loop happens in one call into C, so no per-pair Python
 * overhead reaches the measurement.  Only the matched filter is exposed: there is
 * no transform plan to hand out, because callers bring their own spectra. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdlib.h>
#include "matchedfilter.h"
#include "transform.h"

/* nbins for an hmf plan; the public one takes the plan type directly */
static size_t ap_mf_nbins_hmf_probe(ap_hmf_plan *p,size_t bs,size_t st,size_t en){
  return ap_hmf_nbins(p,bs,st,en);
}

/* ---------------- matched filter ---------------- */
typedef struct { PyObject_HEAD ap_mf_plan *p; Py_ssize_t n; int nd,nt; } MFObject;

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
  size_t nb=ap_mf_nbins(self->p,(size_t)binsize,(size_t)start,(size_t)end);
  Py_ssize_t rows=(Py_ssize_t)nd*nt, need=(Py_ssize_t)(rows*(Py_ssize_t)nb);
  PyObject *err=NULL;
  if(bidx.len<need*8 || bval.len<need*8 || bmag.len<need*4 || bcnt.len<rows*4)
    err=PyErr_Format(PyExc_ValueError,"output arrays too small for %zd pairs x %zu bins",rows,nb);
  if(err){ PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
           PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return NULL; }
  ap_peak *pk=(ap_peak*)PyMem_Malloc((size_t)need*sizeof(ap_peak));
  if(!pk){ PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
           PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return PyErr_NoMemory(); }
  int tot;
  Py_BEGIN_ALLOW_THREADS
  tot=ap_mf_run(self->p,d0,nd,t0,nt,(size_t)binsize,(float)thr,pk,(int*)bcnt.buf,
                (size_t)start,(size_t)end);
  Py_END_ALLOW_THREADS
  if(tot>=0){
    long long *ix=(long long*)bidx.buf; float *vl=(float*)bval.buf,*mg=(float*)bmag.buf;
    for(Py_ssize_t a=0;a<need;a++){
      ix[a]=(long long)pk[a].index; vl[2*a]=pk[a].re; vl[2*a+1]=pk[a].im; mg[a]=pk[a].magnitude;
    }
  }
  PyMem_Free(pk);
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
  int nblocks=(int)(bst.len/(Py_ssize_t)sizeof(size_t));
  size_t nseries=(size_t)(bs.len/(2*sizeof(float)));
  size_t nb=ap_mf_nbins(self->p,(size_t)binsize,
                        ((const size_t*)bws.buf)[0],
                        ((const size_t*)bwe.buf)[0]);
  Py_ssize_t need=(Py_ssize_t)nblocks*nt*(Py_ssize_t)nb;
  ap_peak *pk=(ap_peak*)PyMem_Malloc((size_t)need*sizeof(ap_peak));
  if(!pk){ PyBuffer_Release(&bs);PyBuffer_Release(&bst);PyBuffer_Release(&bws);
           PyBuffer_Release(&bwe);PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
           PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return PyErr_NoMemory(); }
  int tot;
  Py_BEGIN_ALLOW_THREADS
  tot=ap_mf_run_series(self->p,(const float*)bs.buf,nseries,
                       (const size_t*)bst.buf,(const size_t*)bws.buf,
                       (const size_t*)bwe.buf,nblocks,t0,nt,(size_t)binsize,
                       (float)thr,pk,(int*)bcnt.buf);
  Py_END_ALLOW_THREADS
  if(tot>=0){
    long long *ix=(long long*)bidx.buf; float *vl=(float*)bval.buf,*mg=(float*)bmag.buf;
    for(Py_ssize_t a=0;a<need;a++){
      ix[a]=(long long)pk[a].index; vl[2*a]=pk[a].re; vl[2*a+1]=pk[a].im; mg[a]=pk[a].magnitude;
    }
  }
  PyMem_Free(pk);
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
typedef struct { PyObject_HEAD ap_hmf_plan *p; Py_ssize_t n; int nd,nt; } HMFObject;

static int HMF_init(HMFObject *self,PyObject *args,PyObject *kw){
  Py_ssize_t n; int nd,nt; double snr,fd; (void)kw;
  Py_ssize_t band=0; int u=0,k=0;
  if(!PyArg_ParseTuple(args,"niidd|nii",&n,&nd,&nt,&snr,&fd,&band,&u,&k)) return -1;
  /* band/oversample/taps are required: the choice belongs to the measured
     tuning tables, which the Python class reads and which refuse rather than
     guess outside their coverage. */
  if(!band){ PyErr_SetString(PyExc_ValueError,
      "band, oversample and taps are required; HierarchicalFilter picks them "
      "from the tuning tables"); return -1; }
  self->p = ap_hmf_create_ex((size_t)n,nd,nt,(float)snr,(float)fd,(size_t)band,u,k);
  if(!self->p){ PyErr_Format(PyExc_ValueError,
      "no hierarchical plan for n=%zd band=%zd u=%d k=%d",n,band,u,k); return -1; }
  self->n=n; self->nd=nd; self->nt=nt; return 0;
}
static void HMF_dealloc(HMFObject *self){
  if(self->p) ap_hmf_destroy(self->p);
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
  size_t nb=ap_hmf_nbins(self->p,(size_t)binsize,(size_t)start,(size_t)end);
  Py_ssize_t rows=(Py_ssize_t)nd*nt, need=(Py_ssize_t)(rows*(Py_ssize_t)nb);
  if(bidx.len<need*8 || bval.len<need*8 || bmag.len<need*4 || bcnt.len<rows*4){
    PyErr_Format(PyExc_ValueError,"output arrays too small for %zd pairs x %zu bins",rows,nb);
    PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
    PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return NULL; }
  ap_peak *pk=(ap_peak*)PyMem_Malloc((size_t)need*sizeof(ap_peak));
  if(!pk){ PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
           PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return PyErr_NoMemory(); }
  int tot;
  Py_BEGIN_ALLOW_THREADS
  tot=ap_hmf_run(self->p,d0,nd,t0,nt,(size_t)binsize,(float)thr,pk,(int*)bcnt.buf,
                 (size_t)start,(size_t)end);
  Py_END_ALLOW_THREADS
  if(tot>=0){
    long long *ix=(long long*)bidx.buf; float *vl=(float*)bval.buf,*mg=(float*)bmag.buf;
    for(Py_ssize_t a=0;a<need;a++){
      ix[a]=(long long)pk[a].index; vl[2*a]=pk[a].re; vl[2*a+1]=pk[a].im; mg[a]=pk[a].magnitude;
    }
  }
  PyMem_Free(pk);
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
  int nblocks=(int)(bst.len/(Py_ssize_t)sizeof(size_t));
  size_t nseries=(size_t)(bs.len/(2*sizeof(float)));
  size_t nb=ap_mf_nbins_hmf_probe(self->p,(size_t)binsize,
                                  ((const size_t*)bws.buf)[0],
                                  ((const size_t*)bwe.buf)[0]);
  Py_ssize_t need=(Py_ssize_t)nblocks*nt*(Py_ssize_t)nb;
  ap_peak *pk=(ap_peak*)PyMem_Malloc((size_t)need*sizeof(ap_peak));
  if(!pk){ PyBuffer_Release(&bs);PyBuffer_Release(&bst);PyBuffer_Release(&bws);
           PyBuffer_Release(&bwe);PyBuffer_Release(&bidx);PyBuffer_Release(&bval);
           PyBuffer_Release(&bmag);PyBuffer_Release(&bcnt); return PyErr_NoMemory(); }
  int tot;
  Py_BEGIN_ALLOW_THREADS
  tot=ap_hmf_run_series(self->p,(const float*)bs.buf,nseries,
                        (const size_t*)bst.buf,(const size_t*)bws.buf,
                        (const size_t*)bwe.buf,nblocks,t0,nt,(size_t)binsize,
                        (float)thr,pk,(int*)bcnt.buf);
  Py_END_ALLOW_THREADS
  if(tot>=0){
    long long *ix=(long long*)bidx.buf; float *vl=(float*)bval.buf,*mg=(float*)bmag.buf;
    for(Py_ssize_t a=0;a<need;a++){
      ix[a]=(long long)pk[a].index; vl[2*a]=pk[a].re; vl[2*a+1]=pk[a].im; mg[a]=pk[a].magnitude;
    }
  }
  PyMem_Free(pk);
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
static PyObject *HMF_coarse_thresholds(HMFObject *self,PyObject *args){
  float thr,margin=0,raw=0,even=0;
  if(!PyArg_ParseTuple(args,"f",&thr)) return NULL;
  if(ap_hmf_coarse_thresholds(self->p,thr,&margin,&raw,&even)<0){
    PyErr_SetString(PyExc_RuntimeError,"coarse_thresholds failed"); return NULL; }
  return Py_BuildValue("(fff)",margin,raw,even);
}
static PyObject *HMF_config(HMFObject *self,PyObject *a){
  size_t band=0; int u=0,k=0; (void)a; ap_hmf_config(self->p,&band,&u,&k);
  return Py_BuildValue("(nii)",(Py_ssize_t)band,u,k);
}
static PyObject *HMF_set_coarse_margin(HMFObject *self,PyObject *args){
  float g; if(!PyArg_ParseTuple(args,"f",&g)) return NULL;
  if(ap_hmf_set_coarse_margin(self->p,g)<0){
    PyErr_SetString(PyExc_RuntimeError,"set_coarse_margin failed"); return NULL; }
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
  {"set_coarse_margin",(PyCFunction)HMF_set_coarse_margin,METH_VARARGS,"set_coarse_margin(g)"},
  {"run",(PyCFunction)HMF_run,METH_VARARGS,"run(...) -> total crossings"},
  {"nbins",(PyCFunction)HMF_nbins,METH_VARARGS,"nbins(binsize, start, end)"},
  {"run_series",(PyCFunction)HMF_run_series,METH_VARARGS,"run_series(...)"},
  {"stats",(PyCFunction)HMF_stats,METH_NOARGS,"stats() -> (pairs, triggers)"},
  {"config",(PyCFunction)HMF_config,METH_NOARGS,"config() -> (band, oversample, taps)"},
  {"coarse_thresholds",(PyCFunction)HMF_coarse_thresholds,METH_VARARGS,NULL},
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
