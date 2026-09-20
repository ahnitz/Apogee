/* apogee Python extension: the matched filter.
 *
 * The whole D x T pair loop happens in one call into C, so no per-pair Python
 * overhead reaches the measurement.  Only the matched filter is exposed: there is
 * no transform plan to hand out, because callers bring their own spectra. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdlib.h>
#include "apogee.h"
#include "transform.h"

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
  if(tot<0){ PyErr_SetString(PyExc_RuntimeError,"apogee: matched filter failed"); return NULL; }
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
  {"nbins",(PyCFunction)MF_nbins,METH_VARARGS,"nbins(binsize, start, end)"},
  {NULL}
};
static PyTypeObject MFType={
  PyVarObject_HEAD_INIT(NULL,0)
  .tp_name="apogee._core.MF", .tp_basicsize=sizeof(MFObject),
  .tp_flags=Py_TPFLAGS_DEFAULT, .tp_new=PyType_GenericNew,
  .tp_init=(initproc)MF_init, .tp_dealloc=(destructor)MF_dealloc,
  .tp_methods=MF_methods, .tp_doc="apogee matched filter (opaque)",
};

static PyMethodDef methods[]={{NULL,NULL,0,NULL}};
static struct PyModuleDef mod={PyModuleDef_HEAD_INIT,"apogee._core",NULL,-1,methods};
PyMODINIT_FUNC PyInit__core(void){
  if(PyType_Ready(&MFType)<0) return NULL;
  PyObject *m=PyModule_Create(&mod);
  if(!m) return NULL;
  Py_INCREF(&MFType);   PyModule_AddObject(m,"MF",(PyObject*)&MFType);
  return m;
}
