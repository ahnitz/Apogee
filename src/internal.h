#ifndef PF_INTERNAL_H
#define PF_INTERNAL_H
#include <immintrin.h>
#include <stddef.h>
#include "peakfft.h"

/* 1024-point FFT, in place on 64-byte-aligned SoA arrays re[1024], im[1024].
   Input index n = n2*32 + n1 (n1 fast); output in natural order k = k1*32 + k2. */
void pf_fft1024_soa(float *re, float *im,
                    const __m512 (*t4r)[32], const __m512 (*t4i)[32]);
/* Same transform, but also returns the 16 per-lane maxima of |X|^2, accumulated
   from registers inside the final stage.  pf_topk uses them as a scan threshold,
   which costs it no pass of its own. */
void pf_fft1024_soa_mag(float *re, float *im,
                        const __m512 (*t4r)[32], const __m512 (*t4i)[32],
                        __m512 *vmax);

/* AoS interleaved complex <-> SoA, vectorised.  pf_deint_c conjugates as it goes,
   which is how the backward transform is realised: backward(x) = conj(fwd(conj(x))),
   so the conjugations fold into passes that already exist and cost nothing. */
void pf_deint(const float *in, float *re, float *im, size_t n);
void pf_deint_c(const float *in, float *re, float *im, size_t n, int conj);
void pf_inter(const float *re, const float *im, float *out, size_t n);
void pf_inter_c(const float *re, const float *im, float *out, size_t n, int conj);

/* Cheap lower bound on the K-th largest |X|^2 over an SoA block, used to prime the
   scan threshold.  Returns the minimum of the 16 per-lane maxima, which is the
   smallest of 16 actual array elements and therefore never exceeds the 16th largest
   value - so it is a safe threshold for any K <= 16.  Returns -1 for K > 16. */
float pf_prime_threshold(const float *re,const float *im,int n,int K);

/* Running top-K by magnitude-squared (min-heap of size K). */
typedef struct { float mag2; int idx; float re, im; } pf_cand;
void pf_push(pf_cand *T, int K, int *n, float m2, int idx, float vr, float vi);

/* Generic element-space Stockham FFT: the 16 SIMD lanes are independent
   transforms, so every twiddle is a broadcast and no shuffles occur.
   Result lands in X for an even stage count, else in Y (return value says which). */
int elem_fft_generic(int M,__m512*Xr,__m512*Xi,__m512*Yr,__m512*Yi,
                     const float*wr,const float*wi);

/* N = 2^12..2^16 back end (balanced split, L2-resident, fp32 intermediate). */
typedef struct PS PS;
PS  *pfs_create(size_t N);
void pfs_destroy(PS*);
void pfs_exact(PS*,const float*in,float*out,int conj);
int  pfs_topk (PS*,const float*in,int K,pf_peak*out,int conj);

/* N=2^20 back end. */
typedef struct P20 P20;
P20 *pf20_create(size_t N);
void pf20_destroy(P20 *);
void pf20_exact(P20 *, const float *in, float *out, int conj);
int  pf20_topk(P20 *, const float *in, int K, pf_peak *out, int conj);

#endif
