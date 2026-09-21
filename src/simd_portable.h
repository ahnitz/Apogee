/* Portable SIMD layer: GCC/Clang vector extensions instead of x86 intrinsics.
 *
 * The point is to let the compiler pick the instructions.  Vector extensions
 * are supported by both GCC and Clang and lower to whatever the target has --
 * AVX2 or AVX-512 on x86, NEON on arm64 -- so one source covers macOS and
 * Linux without a second set of kernels.
 *
 * The bar this has to clear is set by the AVX2 intrinsics it replaces: no
 * measurable loss against an AVX2-only build.  Whether it clears it is an
 * empirical question, so anything here that turns out slower gets a
 * target-specific specialisation rather than a shrug.
 *
 * FMA comes from contraction: `a*b+c` written as one expression is fused when
 * the target has FMA.  That needs -ffp-contract=fast (GCC's default; Clang's
 * default of `on` also fuses within a single statement).  If contraction is
 * ever disabled this quietly becomes mul+add and loses roughly a third of the
 * arithmetic throughput, so AP_PORTABLE_CHECK_FMA exists to catch it.
 */
#ifndef AP_SIMD_PORTABLE_H
#define AP_SIMD_PORTABLE_H
#include <stdint.h>
#include <string.h>

typedef float vf __attribute__((vector_size(AP_W * 4)));
typedef int32_t vi __attribute__((vector_size(AP_W * 4)));

/* Unaligned access through memcpy.  Both compilers turn a fixed-size memcpy
   into a single unaligned vector load; taking the address of a vector and
   casting would be a strict-aliasing violation for the same result. */
static inline vf v_loadu(const float *p) { vf v; memcpy(&v, p, sizeof v); return v; }
static inline void v_storeu(float *p, vf v) { memcpy(p, &v, sizeof v); }

static inline vf v_set1(float x) {
  vf v;
  for (int i = 0; i < AP_W; i++) v[i] = x;
  return v;
}
static inline vi vi_set1(int32_t x) {
  vi v;
  for (int i = 0; i < AP_W; i++) v[i] = x;
  return v;
}

#define V_ZERO()        v_set1(0.0f)
#define V_SET1(x)       v_set1(x)
#define V_LOAD(p)       v_loadu(p)
#define V_LOADU(p)      v_loadu(p)
#define V_STORE(p,v)    v_storeu(p,v)
#define V_STOREU(p,v)   v_storeu(p,v)
#define V_ADD(a,b)      ((a)+(b))
#define V_SUB(a,b)      ((a)-(b))
#define V_MUL(a,b)      ((a)*(b))
/* Single expressions so the contraction pass can fuse each one. */
#define V_FMADD(a,b,c)  ((a)*(b)+(c))
#define V_FMSUB(a,b,c)  ((a)*(b)-(c))
#define V_FNMADD(a,b,c) ((c)-(a)*(b))
#define V_FNMSUB(a,b,c) (-((a)*(b))-(c))

#define VI_SET1(x)      vi_set1(x)
#define VI_STOREU(p,v)  memcpy((p),&(v),sizeof(v))

/* Bit operations need an integer view; the casts are reinterpretations, which
   is what the vector-extension cast syntax means (unlike __builtin_convertvector). */
#define V_XOR(a,b)      ((vf)((vi)(a) ^ (vi)(b)))
#define V_SIGNMASK()    ((vf)vi_set1((int32_t)0x80000000))

static inline vi v_lanebits(void) {
  vi b;
  for (int i = 0; i < AP_W; i++) b[i] = 1 << i;
  return b;
}

/* Lane comparison as a bitmask.  There is no portable movemask, so this is a
   loop; it sits behind __builtin_expect(...,0) in the peak scan, which is why
   it can afford to be. */
static inline unsigned v_gt_mask(vf a, vf b) {
  vi m = (vi)(a > b);
  unsigned r = 0;
  for (int i = 0; i < AP_W; i++) r |= (unsigned)(m[i] & 1) << i;
  return r;
}

/* Expand the bitmask back to a lane mask by testing each lane's bit, then
   select by bit arithmetic.  The obvious per-lane ternary compiles to a
   scalar insert per lane. */
static inline vi v_maskof(unsigned m) {
  vi bits = v_lanebits();
  return (vi)((vi_set1((int32_t)m) & bits) == bits);
}

/* Shuffles.  Element-by-element vector writes compile to a chain of
   vinsertps (one scalar insert per lane), which is what made the first
   version of this header 2.4x slower than the intrinsics.  Both compilers
   have a two-input shuffle with compile-time indices; they spell it
   differently but index identically, into the concatenation of a and b. */
#if defined(__clang__)
#define AP_SHUF2(a,b,...) __builtin_shufflevector(a,b,__VA_ARGS__)
#else
#define AP_SHUF2(a,b,...) __builtin_shuffle(a,b,(vi){__VA_ARGS__})
#endif

#if AP_W == 8
/* The same network the AVX2 intrinsics use, written as index lists: an
   unpack stage, a 2x2 block shuffle, then a 128-bit lane swap. */
static inline void v_transpose(const vf *in, vf *out) {
  vf t[8], u[8];
  for (int i = 0; i < 8; i += 2) {
    t[i]   = AP_SHUF2(in[i], in[i+1], 0, 8, 1, 9, 4, 12, 5, 13);
    t[i+1] = AP_SHUF2(in[i], in[i+1], 2, 10, 3, 11, 6, 14, 7, 15);
  }
  for (int i = 0; i < 4; i++) {
    int a = (i & 1) + ((i & 2) << 1);       /* 0,1,4,5 */
    int b = a + 2;
    u[2*i]   = AP_SHUF2(t[a], t[b], 0, 1, 8, 9, 4, 5, 12, 13);
    u[2*i+1] = AP_SHUF2(t[a], t[b], 2, 3, 10, 11, 6, 7, 14, 15);
  }
  for (int i = 0; i < 4; i++) {
    out[i]   = AP_SHUF2(u[i], u[i+4], 0, 1, 2, 3, 8, 9, 10, 11);
    out[i+4] = AP_SHUF2(u[i], u[i+4], 4, 5, 6, 7, 12, 13, 14, 15);
  }
}

static inline void v_deint(const float *p, vf *re, vf *im) {
  vf a = v_loadu(p), b = v_loadu(p + 8);
  *re = AP_SHUF2(a, b, 0, 2, 4, 6, 8, 10, 12, 14);
  *im = AP_SHUF2(a, b, 1, 3, 5, 7, 9, 11, 13, 15);
}
static inline void v_inter(float *p, vf re, vf im) {
  v_storeu(p,     AP_SHUF2(re, im, 0, 8, 1, 9, 2, 10, 3, 11));
  v_storeu(p + 8, AP_SHUF2(re, im, 4, 12, 5, 13, 6, 14, 7, 15));
}
#else
/* Other widths fall back to element moves.  Correct, and slow in the way
   described above; add an index list here before using such a width. */
static inline void v_transpose(const vf *in, vf *out) {
  for (int r = 0; r < AP_W; r++)
    for (int c = 0; c < AP_W; c++) out[r][c] = in[c][r];
}
static inline void v_deint(const float *p, vf *re, vf *im) {
  vf r, i;
  for (int k = 0; k < AP_W; k++) { r[k] = p[2*k]; i[k] = p[2*k+1]; }
  *re = r; *im = i;
}
static inline void v_inter(float *p, vf re, vf im) {
  for (int k = 0; k < AP_W; k++) { p[2*k] = re[k]; p[2*k+1] = im[k]; }
}
#endif
#define V_TRANSPOSE(in,out) v_transpose((in),(out))

/* Opaque lane mask: an integer vector of 0 / -1, which is what a vector
   comparison already produces.  Comparing and selecting never touches a
   bitmask, which is what the bitmask round trip cost. */
typedef vi vm;
#define V_CMP_GT(a,b)        ((vi)((a) > (b)))
#define V_MASK_FROM_BITS(u)  v_maskof(u)
#define V_SEL(m,a,b)         ((vf)(((m) & (vi)(b)) | (~(m) & (vi)(a))))
#define VI_SEL(m,a,b)        (((m) & (b)) | (~(m) & (a)))

/* "Did any lane compare true".  There is no portable movemask; fold the
   vector in halves instead, which is log2(W) shuffles rather than W scalar
   extracts. */
static inline int v_mask_any(vi m) {
#if defined(__clang__)
  return __builtin_reduce_or(m) != 0;
#elif AP_W == 8
  vi t = m | AP_SHUF2(m, m, 4, 5, 6, 7, 0, 1, 2, 3);
  t = t | AP_SHUF2(t, t, 2, 3, 0, 1, 6, 7, 4, 5);
  t = t | AP_SHUF2(t, t, 1, 0, 3, 2, 5, 4, 7, 6);
  return t[0] != 0;
#else
  int r = 0;
  for (int i = 0; i < AP_W; i++) r |= m[i];
  return r != 0;
#endif
}
#define V_MASK_ANY(m) v_mask_any(m)

static inline float v_reduce_max(vf v) {
  float m = v[0];
  for (int i = 1; i < AP_W; i++) if (v[i] > m) m = v[i];
  return m;
}
#endif
