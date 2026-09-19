/* CPython extension for peakfft.  Uses only the buffer protocol, so numpy is a
   runtime dependency, not a build-time one. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include "peakfft.h"

typedef struct { PyObject_HEAD pf_plan *p; Py_ssize_t n; } PlanObject;

static void Plan_dealloc(PlanObject *self){
  if(self->p) pf_destroy(self->p);
  Py_TYPE(self)->tp_free((PyObject*)self);
}
static int Plan_init(PlanObject *self,PyObject *args,PyObject *kw){
  Py_ssize_t n;
  static char *kws[]={"n",NULL};
  if(!PyArg_ParseTupleAndKeywords(args,kw,"n",kws,&n)) return -1;
  if(n<=0 || !pf_supported((size_t)n)){
    PyErr_Format(PyExc_ValueError,
      "unsupported transform length %zd; peakfft supports 1024 and 4096..1048576 "
      "(powers of two)",n);
    return -1;
  }
  self->p=pf_create((size_t)n); self->n=n;
  if(!self->p){ PyErr_NoMemory(); return -1; }
  return 0;
}
static PyObject *Plan_len(PlanObject *self,void *c){ (void)c; return PyLong_FromSsize_t(self->n); }
static PyGetSetDef Plan_getset[]={{"n",(getter)Plan_len,NULL,"transform length",NULL},{NULL}};

/* fft(plan, in, out, sign) */
static PyObject *m_fft(PyObject *m,PyObject *args){
  PlanObject *pl; Py_buffer bi,bo; int sign;
  (void)m;
  if(!PyArg_ParseTuple(args,"Oy*w*i",(PyObject**)&pl,&bi,&bo,&sign)) return NULL;
  Py_ssize_t need=pl->n*2*(Py_ssize_t)sizeof(float);
  if(bi.len<need||bo.len<need){
    PyBuffer_Release(&bi); PyBuffer_Release(&bo);
    return PyErr_Format(PyExc_ValueError,"buffers must hold %zd complex64 samples",pl->n);
  }
  Py_BEGIN_ALLOW_THREADS
  pf_fft(pl->p,(const float*)bi.buf,(float*)bo.buf,sign);
  Py_END_ALLOW_THREADS
  PyBuffer_Release(&bi); PyBuffer_Release(&bo);
  Py_RETURN_NONE;
}

/* topk(plan, in, k, idx, val, mag, sign) -> number written */
static PyObject *m_topk(PyObject *m,PyObject *args){
  PlanObject *pl; Py_buffer bi,bidx,bval,bmag; int k,sign;
  (void)m;
  if(!PyArg_ParseTuple(args,"Oy*iw*w*w*i",(PyObject**)&pl,&bi,&k,&bidx,&bval,&bmag,&sign))
    return NULL;
  PyObject *err=NULL;
  if(bi.len < pl->n*2*(Py_ssize_t)sizeof(float))
    err=PyErr_Format(PyExc_ValueError,"input must hold %zd complex64 samples",pl->n);
  else if(k<1||k>PF_MAX_K)
    err=PyErr_Format(PyExc_ValueError,"k must be between 1 and %d",PF_MAX_K);
  if(err){ PyBuffer_Release(&bi);PyBuffer_Release(&bidx);
           PyBuffer_Release(&bval);PyBuffer_Release(&bmag); return NULL; }
  pf_peak peaks[PF_MAX_K]; int n;
  Py_BEGIN_ALLOW_THREADS
  n=pf_topk(pl->p,(const float*)bi.buf,k,peaks,sign);
  Py_END_ALLOW_THREADS
  long long *ix=(long long*)bidx.buf; float *vl=(float*)bval.buf, *mg=(float*)bmag.buf;
  for(int a=0;a<n;a++){ ix[a]=(long long)peaks[a].index;
    vl[2*a]=peaks[a].re; vl[2*a+1]=peaks[a].im; mg[a]=peaks[a].magnitude; }
  PyBuffer_Release(&bi);PyBuffer_Release(&bidx);PyBuffer_Release(&bval);PyBuffer_Release(&bmag);
  return PyLong_FromLong(n);
}

static PyTypeObject PlanType={
  PyVarObject_HEAD_INIT(NULL,0)
  .tp_name="peakfft._core.Plan", .tp_basicsize=sizeof(PlanObject),
  .tp_flags=Py_TPFLAGS_DEFAULT, .tp_new=PyType_GenericNew,
  .tp_init=(initproc)Plan_init, .tp_dealloc=(destructor)Plan_dealloc,
  .tp_getset=Plan_getset, .tp_doc="peakfft plan (opaque)",
};
static PyMethodDef methods[]={
  {"fft",m_fft,METH_VARARGS,"fft(plan, in, out, sign)"},
  {"topk",m_topk,METH_VARARGS,"topk(plan, in, k, idx, val, mag, sign) -> n"},
  {NULL,NULL,0,NULL}
};
static struct PyModuleDef mod={PyModuleDef_HEAD_INIT,"peakfft._core",NULL,-1,methods};
PyMODINIT_FUNC PyInit__core(void){
  if(PyType_Ready(&PlanType)<0) return NULL;
  PyObject *m=PyModule_Create(&mod);
  if(!m) return NULL;
  Py_INCREF(&PlanType);
  PyModule_AddObject(m,"Plan",(PyObject*)&PlanType);
  PyModule_AddIntConstant(m,"FORWARD",PF_FORWARD);
  PyModule_AddIntConstant(m,"BACKWARD",PF_BACKWARD);
  PyModule_AddIntConstant(m,"MAX_K",PF_MAX_K);
  return m;
}
