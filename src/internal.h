#ifndef PF_INTERNAL_H
#define PF_INTERNAL_H
#include <immintrin.h>
#include <stddef.h>

/* 1024-point FFT, in place on 64-byte-aligned SoA arrays re[1024], im[1024].
   Input index n = n2*32 + n1 (n1 fast); output in natural order k = k1*32 + k2. */
void pf_fft1024_soa(float *re, float *im,
                    const __m512 (*t4r)[32], const __m512 (*t4i)[32]);

/* AoS interleaved complex <-> SoA, vectorised. */
void pf_deint(const float *in, float *re, float *im, size_t n);
void pf_inter(const float *re, const float *im, float *out, size_t n);

/* Cheap lower bound on the K-th largest |X|^2 over an SoA block, used to prime the
   scan threshold.  Returns the minimum of the 16 per-lane maxima, which is the
   smallest of 16 actual array elements and therefore never exceeds the 16th largest
   value - so it is a safe threshold for any K <= 16.  Returns -1 for K > 16. */
float pf_prime_threshold(const float *re,const float *im,int n,int K);

/* Running top-K by magnitude-squared (min-heap of size K). */
typedef struct { float mag2; int idx; float re, im; } pf_cand;
void pf_push(pf_cand *T, int K, int *n, float m2, int idx, float vr, float vi);

/* N=2^20 back end. */
typedef struct P20 P20;
P20 *pf20_create(void);
void pf20_destroy(P20 *);
void pf20_exact(P20 *, const float *in, float *out);
int  pf20_topk(P20 *, const float *in, int K, int *idx, float *re, float *im);

#endif
