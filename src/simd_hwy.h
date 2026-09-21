/* SIMD layer on Google Highway.
 *
 * Same V_* surface as the intrinsic and vector-extension layers, so
 * codelets.h and balanced.c are unchanged -- they only ever spoke through
 * these macros.  Highway lowers each op to the target's intrinsics, which
 * matters for more than portability: the GCC SLP pass re-vectorised the plain
 * vector-extension arithmetic and cost 2.3x, and intrinsics are opaque to it.
 *
 * AP_W must be the target's native lane count.  Highway's FixedTag rejects a
 * width wider than the target vector, so the build picks AP_W per target:
 * 16 for AVX-512, 8 for AVX2, 4 for NEON and SSE4.  codelets.h is
 * width-neutral, so only this file and a handful of masks care.
 *
 * Every function using these must carry HWY_ATTR, and the translation unit
 * must sit between HWY_BEFORE_NAMESPACE and HWY_AFTER_NAMESPACE: Highway's
 * ops are always_inline with target attributes, and a caller without them
 * fails to inline rather than falling back.
 */
#ifndef AP_SIMD_HWY_H
#define AP_SIMD_HWY_H
#include <string.h>
#include "hwy/highway.h"

namespace hn = hwy::HWY_NAMESPACE;

using ap_tag  = hn::FixedTag<float, AP_W>;
using ap_itag = hn::FixedTag<int32_t, AP_W>;
static constexpr ap_tag  AP_D{};
static constexpr ap_itag AP_DI{};

#if AP_W == 4
#define AP_LOG2W 2
#elif AP_W == 8
#define AP_LOG2W 3
#elif AP_W == 16
#define AP_LOG2W 4
#else
#error "AP_W must be 4, 8 or 16"
#endif

typedef hn::Vec<ap_tag>  vf;
typedef hn::Vec<ap_itag> vi;
typedef decltype(hn::Gt(hn::Zero(AP_D), hn::Zero(AP_D))) vm;

#define V_ZERO()        hn::Zero(AP_D)
#define V_SET1(x)       hn::Set(AP_D, (float)(x))
#define V_LOAD(p)       hn::LoadU(AP_D, (p))
#define V_LOADU(p)      hn::LoadU(AP_D, (p))
#define V_STORE(p, v)   hn::StoreU((v), AP_D, (p))
#define V_STOREU(p, v)  hn::StoreU((v), AP_D, (p))
#define V_ADD(a, b)     hn::Add((a), (b))
#define V_SUB(a, b)     hn::Sub((a), (b))
#define V_MUL(a, b)     hn::Mul((a), (b))
#define V_FMADD(a,b,c)  hn::MulAdd((a), (b), (c))          /*  a*b + c */
#define V_FMSUB(a,b,c)  hn::MulSub((a), (b), (c))          /*  a*b - c */
#define V_FNMADD(a,b,c) hn::NegMulAdd((a), (b), (c))       /* -a*b + c */
#define V_FNMSUB(a,b,c) hn::NegMulSub((a), (b), (c))       /* -a*b - c */

#define VI_SET1(x)      hn::Set(AP_DI, (int32_t)(x))
#define VI_STOREU(p, v) hn::StoreU((v), AP_DI, (int32_t *)(p))

/* Sign flip by xor, as the callers expect: they build a sign mask and xor it
   rather than negating, because the mask is loop-invariant. */
#define V_SIGNMASK()    hn::BitCast(AP_D, hn::Set(AP_DI, (int32_t)0x80000000))
#define V_XOR(a, b)     hn::Xor((a), (b))

/* Opaque lane mask: native on AVX-512, a vector mask elsewhere.  Comparing
   and selecting never materialises bits, which is what the bitmask round trip
   used to cost. */
#define V_CMP_GT(a, b)  hn::Gt((a), (b))
#define V_MASK_ANY(m)   (!hn::AllFalse(AP_D, (m)))
/* select b where the mask is set, a where clear */
#define V_SEL(m, a, b)  hn::IfThenElse((m), (b), (a))
#define VI_SEL(m, a, b) hn::IfThenElse(hn::RebindMask(AP_DI, (m)), (b), (a))

static HWY_ATTR HWY_INLINE vm ap_mask_from_bits(unsigned bits) {
  uint64_t b = bits;
  return hn::LoadMaskBits(AP_D, (const uint8_t *)&b);
}
#define V_MASK_FROM_BITS(u) ap_mask_from_bits((unsigned)(u))

static HWY_ATTR HWY_INLINE float v_reduce_max(vf v) {
  return hn::ReduceMax(AP_D, v);
}

/* Deinterleave one vector's worth of complex, and the inverse. */
static HWY_ATTR HWY_INLINE void v_deint(const float *p, vf *re, vf *im) {
  hn::LoadInterleaved2(AP_D, p, *re, *im);
}
static HWY_ATTR HWY_INLINE void v_inter(float *p, vf re, vf im) {
  hn::StoreInterleaved2(re, im, AP_D, p);
}

/* W x W transpose: one network, every width.
 *
 * log2(W) stages.  Stage with pairing distance m takes rows i and i+m and
 * replaces them with the element-wise interleave of the two, m halving from
 * W/2 down to 1.  Verified exact at W = 4, 8 and 16.
 *
 * InterleaveWholeLower/Upper is the whole-vector interleave.  Highway's
 * plain InterleaveLower/Upper act within 128-bit blocks, following the x86
 * instructions they wrap, and building the network from those needs a
 * different index pattern per width plus a bit-reversal of the rows -- two
 * code paths and a subtlety.  This needs neither.
 *
 * Written straight from in[] into out[] with no working array: the caller
 * already holds TR/TI/OR/OI, which is 64 vectors at W=16, and a local copy
 * here spilled.
 */
#if AP_W == 8
/* AVX2 is the primary target, so it gets the one specialisation: block-wise
   interleaves plus a lane swap.  The generic network below is correct here
   too and costs 12% -- on AVX2 a whole-vector interleave crosses 128-bit
   lanes and needs vpermps, while InterleaveLower is one vunpcklps.  On
   AVX-512 the whole interleave is a single vpermt2ps and the generic
   network is the better of the two, so this is a property of the hardware
   rather than a shortcut. */
static HWY_ATTR HWY_INLINE void v_transpose(const vf *in, vf *out) {
  const hn::Repartition<uint64_t, ap_tag> d64;
  vf t[8], u[8];
  for (int i = 0; i < 8; i += 2) {
    t[i]     = hn::InterleaveLower(AP_D, in[i], in[i + 1]);
    t[i + 1] = hn::InterleaveUpper(AP_D, in[i], in[i + 1]);
  }
  for (int i = 0; i < 4; i++) {
    const int a = (i & 1) + ((i & 2) << 1);      /* 0,1,4,5 */
    const int b = a + 2;
    u[2 * i]     = hn::BitCast(AP_D, hn::InterleaveLower(
                     d64, hn::BitCast(d64, t[a]), hn::BitCast(d64, t[b])));
    u[2 * i + 1] = hn::BitCast(AP_D, hn::InterleaveUpper(
                     d64, hn::BitCast(d64, t[a]), hn::BitCast(d64, t[b])));
  }
  for (int i = 0; i < 4; i++) {
    out[i]     = hn::ConcatLowerLower(AP_D, u[i + 4], u[i]);
    out[i + 4] = hn::ConcatUpperUpper(AP_D, u[i + 4], u[i]);
  }
}
#else
static HWY_ATTR HWY_INLINE void v_transpose(const vf *in, vf *out) {
  for (int m = AP_W / 2; m >= 1; m >>= 1) {
    const vf *src = (m == AP_W / 2) ? in : out;
    for (int i = 0; i < AP_W; i++) {
      if (i & m) continue;
      const int j = i | m;
      const vf a = src[i], b = src[j];
      out[i] = hn::InterleaveWholeLower(AP_D, a, b);
      out[j] = hn::InterleaveWholeUpper(AP_D, a, b);
    }
  }
}
#endif
#define V_TRANSPOSE(in, out) v_transpose((in), (out))

#endif
