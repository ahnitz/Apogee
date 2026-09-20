/* Minimal FFTW declarations so the benchmark builds without fftw3-devel headers. */
#ifndef PF_FFTW_MIN_H
#define PF_FFTW_MIN_H
#include <stddef.h>
typedef float fftwf_complex[2];
typedef void *fftwf_plan;
void *fftwf_malloc(size_t);
fftwf_plan fftwf_plan_dft_1d(int,fftwf_complex*,fftwf_complex*,int,unsigned);
void fftwf_execute(fftwf_plan);
fftwf_plan fftwf_plan_many_dft(int rank,const int *n,int howmany,
                               fftwf_complex *in,const int *inembed,int istride,int idist,
                               fftwf_complex *out,const int *onembed,int ostride,int odist,
                               int sign,unsigned flags);
int fftwf_export_wisdom_to_filename(const char*);
int fftwf_import_wisdom_from_filename(const char*);
#define FFTW_FORWARD (-1)
#define FFTW_PATIENT (1U<<5)
#define FFTW_MEASURE 0U
#define fftwf_alloc_complex(n) ((fftwf_complex*)fftwf_malloc(sizeof(fftwf_complex)*(n)))
#endif
