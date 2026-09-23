/* matchedfilter._metal: the Apple GPU back end, as a Python extension.
 *
 * The MF type has the same methods, with the same arguments, as
 * matchedfilter._core.MF, so matchedfilter.metal.MatchedFilter reuses the CPU
 * class's argument handling and output assembly unchanged. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include "mf_metal.h"

typedef struct { PyObject_HEAD mfm_plan *p; Py_ssize_t n; int nd, nt; } MFObject;

static PyObject *metal_error(const char *what) {
  const char *e = mfm_last_error();
  return PyErr_Format(PyExc_RuntimeError, "matchedfilter.metal: %s%s%s", what,
                      e ? ": " : "", e ? e : "");
}

static int MF_init(MFObject *self, PyObject *args, PyObject *kw) {
  Py_ssize_t n; int nd, nt; (void)kw;
  if (!PyArg_ParseTuple(args, "nii", &n, &nd, &nt)) return -1;
  if (!mfm_available()) { metal_error("no usable Metal device"); return -1; }
  if (!mfm_supported((size_t)n) || nd < 1 || nt < 1) {
    PyErr_Format(PyExc_ValueError,
                 "unsupported matched-filter shape n=%zd ndata=%d ntemplates=%d "
                 "(the GPU takes powers of two from 256 to 2^21)", n, nd, nt);
    return -1;
  }
  mfm_plan *p;
  Py_BEGIN_ALLOW_THREADS
  p = mfm_create((size_t)n, nd, nt);
  Py_END_ALLOW_THREADS
  if (!p) { metal_error("could not build the plan"); return -1; }
  self->p = p; self->n = n; self->nd = nd; self->nt = nt;
  return 0;
}

static void MF_dealloc(MFObject *self) {
  if (self->p) mfm_destroy(self->p);
  Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *MF_set(MFObject *self, PyObject *args, int is_data) {
  int i; Py_buffer b;
  if (!PyArg_ParseTuple(args, "iy*", &i, &b)) return NULL;
  if (b.len < self->n * 2 * (Py_ssize_t)sizeof(float)) {
    PyBuffer_Release(&b);
    return PyErr_Format(PyExc_ValueError, "segment must hold %zd complex64 samples", self->n);
  }
  int r;
  Py_BEGIN_ALLOW_THREADS
  r = is_data ? mfm_set_data(self->p, i, (const float *)b.buf)
              : mfm_set_template(self->p, i, (const float *)b.buf);
  Py_END_ALLOW_THREADS
  PyBuffer_Release(&b);
  if (r < 0) return PyErr_Format(PyExc_IndexError, "index %d out of range", i);
  Py_RETURN_NONE;
}
static PyObject *MF_set_data(MFObject *s, PyObject *a) { return MF_set(s, a, 1); }
static PyObject *MF_set_template(MFObject *s, PyObject *a) { return MF_set(s, a, 0); }

/* run(d0,nd,t0,nt,binsize,threshold,start,end, idx,val,mag,counts) -> total */
static PyObject *MF_run(MFObject *self, PyObject *args) {
  int d0, nd, t0, nt; Py_ssize_t binsize, start, end; double thr;
  Py_buffer bidx, bval, bmag, bcnt;
  if (!PyArg_ParseTuple(args, "iiiindnnw*w*w*w*", &d0, &nd, &t0, &nt, &binsize, &thr,
                        &start, &end, &bidx, &bval, &bmag, &bcnt)) return NULL;
  size_t nb = mfm_nbins(self->p, (size_t)binsize, (size_t)start, (size_t)end);
  Py_ssize_t rows = (Py_ssize_t)nd * nt, need = rows * (Py_ssize_t)nb;
  int tot = -2;
  if (bidx.len >= need * 8 && bval.len >= need * 8 && bmag.len >= need * 4 && bcnt.len >= rows * 4) {
    Py_BEGIN_ALLOW_THREADS
    tot = mfm_run(self->p, d0, nd, t0, nt, (size_t)binsize, (float)thr,
                  (size_t)start, (size_t)end, (long long *)bidx.buf,
                  (float *)bval.buf, (float *)bmag.buf, (int *)bcnt.buf);
    Py_END_ALLOW_THREADS
  }
  PyBuffer_Release(&bidx); PyBuffer_Release(&bval);
  PyBuffer_Release(&bmag); PyBuffer_Release(&bcnt);
  if (tot == -2)
    return PyErr_Format(PyExc_ValueError, "output arrays too small for %zd pairs x %zu bins", rows, nb);
  if (tot < 0) return metal_error("run failed");
  return PyLong_FromLong(tot);
}

static PyObject *MF_nbins(MFObject *self, PyObject *args) {
  Py_ssize_t bs, st, en;
  if (!PyArg_ParseTuple(args, "nnn", &bs, &st, &en)) return NULL;
  return PyLong_FromSize_t(mfm_nbins(self->p, (size_t)bs, (size_t)st, (size_t)en));
}

static PyObject *MF_config(MFObject *self, PyObject *noargs) {
  (void)noargs;
  int fs = 0, a = 0, b = 0, w = 0;
  mfm_config(self->p, &fs, &a, &b, &w);
  if (fs) return Py_BuildValue("{s:s,s:i,s:i,s:i}", "path", "four-step", "A", a, "B", b, "W2", w);
  return Py_BuildValue("{s:s,s:i}", "path", "one-pass", "pairs_per_group", a);
}

static PyMethodDef MF_methods[] = {
  {"set_data", (PyCFunction)MF_set_data, METH_VARARGS, "set_data(i, buffer)"},
  {"set_template", (PyCFunction)MF_set_template, METH_VARARGS, "set_template(i, buffer)"},
  {"run", (PyCFunction)MF_run, METH_VARARGS, "run(...) -> total crossings"},
  {"nbins", (PyCFunction)MF_nbins, METH_VARARGS, "nbins(binsize, start, end)"},
  {"config", (PyCFunction)MF_config, METH_NOARGS, "config() -> the kernel shape chosen"},
  {NULL}
};

static PyTypeObject MFType = {
  PyVarObject_HEAD_INIT(NULL, 0)
  .tp_name = "matchedfilter._metal.MF", .tp_basicsize = sizeof(MFObject),
  .tp_flags = Py_TPFLAGS_DEFAULT, .tp_new = PyType_GenericNew,
  .tp_init = (initproc)MF_init, .tp_dealloc = (destructor)MF_dealloc,
  .tp_methods = MF_methods, .tp_doc = "matchedfilter GPU matched filter (opaque)",
};

static PyObject *M_available(PyObject *self, PyObject *noargs) {
  (void)self; (void)noargs;
  return PyBool_FromLong(mfm_available());
}
static PyObject *M_device(PyObject *self, PyObject *noargs) {
  (void)self; (void)noargs;
  const char *d = mfm_device_name();
  if (!d) Py_RETURN_NONE;
  return PyUnicode_FromString(d);
}

static PyObject *M_gpu_seconds(PyObject *self, PyObject *noargs) {
  (void)self; (void)noargs;
  return PyFloat_FromDouble(mfm_last_gpu_seconds());
}

static PyMethodDef methods[] = {
  {"last_gpu_seconds", M_gpu_seconds, METH_NOARGS, "GPU time of the last run, in seconds"},
  {"available", M_available, METH_NOARGS, "available() -> is there a usable Metal GPU"},
  {"device", M_device, METH_NOARGS, "device() -> name of the GPU, or None"},
  {NULL, NULL, 0, NULL}};
static struct PyModuleDef mod = {PyModuleDef_HEAD_INIT, "matchedfilter._metal", NULL, -1, methods};

PyMODINIT_FUNC PyInit__metal(void) {
  if (PyType_Ready(&MFType) < 0) return NULL;
  PyObject *m = PyModule_Create(&mod);
  if (!m) return NULL;
  Py_INCREF(&MFType);
  PyModule_AddObject(m, "MF", (PyObject *)&MFType);
  return m;
}
