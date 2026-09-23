/* matchedfilter on the Apple GPU: Metal kernels.
 *
 * For every pair (d, t)
 *
 *     z[k] = IFFT( D_d[f] * conj(T_t[f]) )[k]        (unnormalised, e^{+2 pi i fk/n})
 *
 * and the loudest |z| in each bin of the window [ws, we) is reported, exactly
 * as the CPU kernels do.  The product is formed inside the first FFT stage's
 * load and the peak search runs on the transform's output while it is still in
 * threadgroup memory, so the full correlation never reaches device memory for
 * n <= 4096, and for longer transforms only one intermediate does.
 *
 * Two paths:
 *
 *   mf_small            n <= 4096.  One threadgroup holds FFT_M whole pairs.
 *
 *   mf_pass1/mf_pass2   n = A * B, four-step.  Spectra are stored row-major
 *   + mf_final_*        [f1][f2] with f = f1 + A*f2, so pass 1 reads each row
 *                       contiguously, does a B-point FFT and applies the
 *                       w_n^{f1 k2} twiddle; pass 2 does the A-point FFTs of W2
 *                       adjacent columns and scans the result.  Pass 2's output
 *                       for one k1 is a "run" of W2 consecutive lags, so a bin
 *                       can straddle threadgroups: each run reports the pieces
 *                       of its first and last bin as partial maxima, bins lying
 *                       wholly inside a run are finished on the spot, and
 *                       mf_final_* merges the pieces.
 *
 * The host compiles this source once per tile shape with these macros:
 *   FFT_L  transform length handled by the threadgroup (power of two)
 *   FFT_M  transforms per threadgroup
 *   IFAST  1: consecutive threads walk the transform index, tile layout m*L+i
 *          0: consecutive threads walk the transform number, layout i*M+m
 *   VPT    complex values held per thread (a power of two >= RADX)
 *   RADX   radix of every stage after the first
 *   NST    number of stages
 *   RAD0   radix of the first stage; FFT_L = RAD0 * RADX^(NST-1)
 */
#include <metal_stdlib>
using namespace metal;

#ifndef FFT_L
#define FFT_L 1024
#define FFT_M 1
#define IFAST 1
#define VPT 16
#define RADX 16
#define NST 3
#define RAD0 4
#endif

#define E_TG  (FFT_M * FFT_L)          /* complex values per threadgroup */
#define T_TG  (E_TG / VPT)             /* threads per threadgroup        */
#define RL    (NST == 1 ? RAD0 : RADX) /* radix of the last stage        */
#define PL    (FFT_L / RL)             /* its sub-transform length p     */

/* Small-path peak search: bins up to CH lags go to a group of lanes each;
   wider ones are split into chunks of CH, one simdgroup per chunk. */
#define CH 128
#define PARTMAX (3 * E_TG / CH + FFT_M + 4)

struct Params {
  uint n;          /* transform length                                   */
  uint ntl;        /* templates in this run (rows are dl*ntl + tl)        */
  uint ndl;        /* data segments in this run                           */
  uint dinner;     /* 1: consecutive pairs share a template, not a segment */
  uint d0, t0;     /* first data segment / template of this run           */
  uint npairs;     /* pairs in this run                                   */
  uint pair0;      /* four-step: first pair of this chunk                 */
  uint nchunk;     /* four-step: pairs in this chunk                      */
  uint nb, bs;     /* bins and bin size                                   */
  uint ws, we;     /* lag window                                          */
  float t2;        /* squared threshold, or -1 to report every bin        */
  uint A, B, W2;   /* four-step shape                                     */
  uint H;          /* split of the four-step twiddle index, m = mh*H + ml */
};

/* Pair pr of the run, in execution order, as (data, template) offsets.
   Consecutive threadgroups share whichever side is iterated outer, so the
   inner side should be the smaller one: it stays cached while the other
   streams through once. */
static inline uint2 pair_dt(uint pr, constant Params &P) {
  return P.dinner ? uint2(pr % P.ndl, pr / P.ndl) : uint2(pr / P.ntl, pr % P.ntl);
}
/* The output row of pair pr: always (d - d0)*nt + (t - t0), as on the CPU. */
static inline ulong out_row(uint pr, constant Params &P) {
  const uint2 dt = pair_dt(pr, P);
  return (ulong)dt.x * P.ntl + dt.y;
}

/* ------------------------------------------------------------ complex */

static inline float2 cmul(float2 a, float2 b) {
  return float2(fma(a.x, b.x, -a.y * b.y), fma(a.x, b.y, a.y * b.x));
}
/* a * conj(b) */
static inline float2 cmulc(float2 a, float2 b) {
  return float2(fma(a.x, b.x, a.y * b.y), fma(a.y, b.x, -a.x * b.y));
}
static inline float2 muli(float2 a) { return float2(-a.y, a.x); }  /* a * i */
static inline float mag2(float2 a) { return fma(a.x, a.x, a.y * a.y); }

/* --------------------------------------------- inverse DFT codelets */
/* All with the backward sign, w_R = e^{+2 pi i / R}, in place.        */

template <int R> static inline void dft(thread float2 *x);

template <> inline void dft<1>(thread float2 *x) { (void)x; }

template <> inline void dft<2>(thread float2 *x) {
  float2 a = x[0], b = x[1];
  x[0] = a + b; x[1] = a - b;
}

template <> inline void dft<4>(thread float2 *x) {
  float2 s0 = x[0] + x[2], d0 = x[0] - x[2];
  float2 s1 = x[1] + x[3], d1 = muli(x[1] - x[3]);
  x[0] = s0 + s1; x[2] = s0 - s1;
  x[1] = d0 + d1; x[3] = d0 - d1;
}

template <> inline void dft<8>(thread float2 *x) {
  const float c = 0.70710678118654752f;
  float2 e[4] = {x[0], x[2], x[4], x[6]};
  float2 o[4] = {x[1], x[3], x[5], x[7]};
  dft<4>(e); dft<4>(o);
  o[1] = float2(c * (o[1].x - o[1].y), c * (o[1].x + o[1].y));   /* * e^{i pi/4}  */
  o[2] = muli(o[2]);                                              /* * i           */
  o[3] = float2(-c * (o[3].x + o[3].y), c * (o[3].x - o[3].y));  /* * e^{3i pi/4} */
  for (int k = 0; k < 4; k++) { x[k] = e[k] + o[k]; x[k + 4] = e[k] - o[k]; }
}

template <> inline void dft<16>(thread float2 *x) {
  const float2 w[8] = {
    float2(1.0f, 0.0f),
    float2(0.92387953251128676f, 0.38268343236508977f),
    float2(0.70710678118654752f, 0.70710678118654752f),
    float2(0.38268343236508977f, 0.92387953251128676f),
    float2(0.0f, 1.0f),
    float2(-0.38268343236508977f, 0.92387953251128676f),
    float2(-0.70710678118654752f, 0.70710678118654752f),
    float2(-0.92387953251128676f, 0.38268343236508977f)};
  float2 e[8], o[8];
  for (int k = 0; k < 8; k++) { e[k] = x[2 * k]; o[k] = x[2 * k + 1]; }
  dft<8>(e); dft<8>(o);
  for (int k = 1; k < 8; k++) o[k] = cmul(o[k], w[k]);
  for (int k = 0; k < 8; k++) { x[k] = e[k] + o[k]; x[k + 8] = e[k] - o[k]; }
}

/* ------------------------------------------- tile FFT (Stockham, in TG) */
/*
 * A stage of radix R with sub-transform length p reads x[i + r*L/R], twiddles
 * by w_{pR}^{r*k} (k = i mod p), does a radix-R DFT and writes
 * y[(i-k)*R + k + r*p].  Starting at p = 1 the output is in natural order.
 * Each thread owns VPT/R such butterflies per stage; values stay in registers
 * and move between stages through threadgroup memory, one real component at a
 * time so the exchange buffer is E_TG floats rather than E_TG complex.
 */

static inline uint taddr(uint m, uint idx) {
  return IFAST ? m * FFT_L + idx : idx * FFT_M + m;
}

template <int R>
static inline void task_mi(uint g, thread uint &m, thread uint &i) {
  const uint per = FFT_L / R;
  if (IFAST) { i = g % per; m = g / per; }
  else       { m = g % FFT_M; i = g / FFT_M; }
}

template <int R>
static inline void stage_compute(thread float2 *v, uint tid, uint p,
                                 device const float2 *tw) {
  for (uint u = 0; u < VPT / R; u++) {
    uint m, i;
    task_mi<R>(tid + u * T_TG, m, i);
    const uint k = i & (p - 1);
    if (p > 1 && k) {
      /* Load w^r only for r a power of two and build the rest from those:
         log2(R) loads instead of R-1, for one extra rounding at most. */
      const uint st = k * (FFT_L / (p * R));
      float2 w[R];
      for (uint r = 1; r < (uint)R; r++) {
        const uint lo = r & (~r + 1u);
        w[r] = lo == r ? tw[r * st] : cmul(w[lo], w[r - lo]);
        v[u * R + r] = cmul(v[u * R + r], w[r]);
      }
    }
    dft<R>(v + u * R);
  }
}

/* output position (within its transform) of value (u, r) after a stage */
template <int R>
static inline uint out_pos(uint tid, uint u, uint r, uint p, thread uint &m) {
  uint i;
  task_mi<R>(tid + u * T_TG, m, i);
  const uint k = i & (p - 1);
  return (i - k) * R + k + r * p;
}

/* input position of value (u, r) for a stage */
template <int R>
static inline uint in_pos(uint tid, uint u, uint r, thread uint &m) {
  uint i;
  task_mi<R>(tid + u * T_TG, m, i);
  return i + r * (FFT_L / R);
}

template <int RA, int RB>
static inline void exchange(thread float2 *v, threadgroup float *buf, uint tid, uint pA) {
  uint m;
  threadgroup_barrier(mem_flags::mem_threadgroup);
  for (uint u = 0; u < VPT / RA; u++)
    for (uint r = 0; r < (uint)RA; r++) {
      uint q = out_pos<RA>(tid, u, r, pA, m);
      buf[taddr(m, q)] = v[u * RA + r].x;
    }
  threadgroup_barrier(mem_flags::mem_threadgroup);
  for (uint u = 0; u < VPT / RB; u++)
    for (uint r = 0; r < (uint)RB; r++) {
      uint q = in_pos<RB>(tid, u, r, m);
      v[u * RB + r].x = buf[taddr(m, q)];
    }
  threadgroup_barrier(mem_flags::mem_threadgroup);
  for (uint u = 0; u < VPT / RA; u++)
    for (uint r = 0; r < (uint)RA; r++) {
      uint q = out_pos<RA>(tid, u, r, pA, m);
      buf[taddr(m, q)] = v[u * RA + r].y;
    }
  threadgroup_barrier(mem_flags::mem_threadgroup);
  for (uint u = 0; u < VPT / RB; u++)
    for (uint r = 0; r < (uint)RB; r++) {
      uint q = in_pos<RB>(tid, u, r, m);
      v[u * RB + r].y = buf[taddr(m, q)];
    }
}

/* Every stage after the first load.  On return value v[u*RL + r] holds output
   index i + r*PL of transform m, where (m, i) = task_mi<RL>(tid + u*T_TG). */
static inline void fft_rest(thread float2 *v, threadgroup float *buf, uint tid,
                            device const float2 *tw) {
  stage_compute<RAD0>(v, tid, 1, tw);
  if (NST > 1) {
    exchange<RAD0, RADX>(v, buf, tid, 1);
    stage_compute<RADX>(v, tid, RAD0, tw);
    uint p = RAD0;
    for (int s = 2; s < NST; s++) {
      exchange<RADX, RADX>(v, buf, tid, p);
      p *= RADX;
      stage_compute<RADX>(v, tid, p, tw);
    }
  }
}

/* The final position of value (u, r), and its transform. */
static inline uint final_pos(uint tid, uint u, uint r, thread uint &m) {
  uint i;
  task_mi<RL>(tid + u * T_TG, m, i);
  return i + r * PL;
}

/* A marker left in the magnitude buffer: magnitudes are >= 0, so a negative
   value says "the value here won; code c tells its owner where to write it". */
static inline float mark(uint c) { return -1.0f - (float)c; }
static inline uint unmark(float x) { return (uint)(-x - 1.0f); }

/* ======================================================== small path */

kernel void mf_small(device const float2 *D     [[buffer(0)]],
                     device const float2 *Tm    [[buffer(1)]],
                     device const float2 *tw    [[buffer(2)]],
                     device int          *oidx  [[buffer(3)]],
                     device float2       *oval  [[buffer(4)]],
                     device float        *omag  [[buffer(5)]],
                     constant Params     &P     [[buffer(6)]],
                     device float2       *gpart [[buffer(7)]],
                     uint tg   [[threadgroup_position_in_grid]],
                     uint tid  [[thread_position_in_threadgroup]],
                     uint lane [[thread_index_in_simdgroup]],
                     uint sg   [[simdgroup_index_in_threadgroup]],
                     uint nsg  [[simdgroups_per_threadgroup]]) {
  /* The exchange buffer takes all of threadgroup memory at E_TG = 8192, so
     the few chunk maxima of a wide-bin search go to device memory instead;
     they are written and read back by this threadgroup only, and stay in
     cache. */
  threadgroup float buf[E_TG];
  device float2 *part = gpart + (ulong)tg * PARTMAX;
  float2 v[VPT];
  const uint n = FFT_L;
  const uint pb = tg * FFT_M;

  /* load, forming D * conj(T) on the way in */
  for (uint u = 0; u < VPT / RAD0; u++) {
    uint m, i;
    task_mi<RAD0>(tid + u * T_TG, m, i);
    const uint pr = pb + m;
    if (pr < P.npairs) {
      const uint2 dt = pair_dt(pr, P);
      device const float2 *dp = D + (ulong)(P.d0 + dt.x) * n;
      device const float2 *tp = Tm + (ulong)(P.t0 + dt.y) * n;
      for (uint r = 0; r < (uint)RAD0; r++) {
        const uint q = i + r * (n / RAD0);
        v[u * RAD0 + r] = cmulc(dp[q], tp[q]);
      }
    } else {
      for (uint r = 0; r < (uint)RAD0; r++) v[u * RAD0 + r] = float2(0.0f);
    }
  }
  fft_rest(v, buf, tid, tw);

  /* |z|^2 into the tile, natural order */
  threadgroup_barrier(mem_flags::mem_threadgroup);
  for (uint u = 0; u < VPT / RL; u++)
    for (uint r = 0; r < (uint)RL; r++) {
      uint m; uint q = final_pos(tid, u, r, m);
      buf[taddr(m, q)] = mag2(v[u * RL + r]);
    }
  threadgroup_barrier(mem_flags::mem_threadgroup);

  const uint nb = P.nb, bs = P.bs, ws = P.ws, we = P.we;
  const float t2 = P.t2;
  const uint npm = min((uint)FFT_M, P.npairs > pb ? P.npairs - pb : 0u);

  if (bs <= CH) {
    /* Bins up to CH lags: a group of G lanes per bin, G sized so no lane reads
       more than four lags, reduced with xor shuffles.  A thread per bin
       serialised the scan for bins of a few dozen lags, and a whole simdgroup
       per bin left most of its lanes idle; this was 2x at binsize 33-64.
       The loop bound is uniform across the simdgroup, so every lane takes
       part in every shuffle. */
    uint G = 1;
    while (G < 32 && G * 4 < bs) G <<= 1;
    const uint gps = 32 / G, gl = lane % G, total = npm * nb;
    for (uint base = sg * gps; base < total; base += nsg * gps) {
      const uint q = base + lane / G;
      float bm = t2; int bk = INT_MAX;
      uint m = 0, j = 0;
      if (q < total) {
        m = q / nb; j = q % nb;
        const uint s = ws + j * bs, e = min(s + bs, we);
        for (uint k = s + gl; k < e; k += G) {
          float x = buf[taddr(m, k)];
          if (x > bm) { bm = x; bk = (int)k; }
        }
      }
      /* the largest, and the lowest lag among equals: a sequential scan's answer */
      for (uint off = 1; off < G; off <<= 1) {
        const float om = simd_shuffle_xor(bm, (ushort)off);
        const int ok = simd_shuffle_xor(bk, (ushort)off);
        if (om > bm || (om == bm && ok < bk)) { bm = om; bk = ok; }
      }
      if (q < total && gl == 0) {
        if (bk != INT_MAX) buf[taddr(m, (uint)bk)] = mark(j);
        else {
          const ulong o = out_row(pb + m, P) * nb + j;
          oidx[o] = -1; oval[o] = float2(0.0f); omag[o] = 0.0f;
        }
      }
    }
  } else {
    /* wide bins: a simdgroup per chunk of CH lags, then merge the chunks */
    const uint nchF = (bs + CH - 1) / CH;
    const uint lastlen = (we - ws) - (nb - 1) * bs;
    const uint NC = (nb - 1) * nchF + (lastlen + CH - 1) / CH;
    for (uint c = sg; c < npm * NC; c += nsg) {
      const uint m = c / NC, cg = c % NC;
      const uint j = cg / nchF, cc = cg % nchF;
      const uint bst = ws + j * bs;
      const uint s = bst + cc * CH;
      const uint e = min(min(s + CH, bst + bs), we);
      float bm = t2; int bk = -1;
      for (uint k = s + lane; k < e; k += 32) {
        float x = buf[taddr(m, k)];
        if (x > bm) { bm = x; bk = (int)k; }
      }
      const float mx = simd_max(bm);
      const int kk = simd_min((bm == mx && bk >= 0) ? bk : INT_MAX);
      if (lane == 0) {
        if (nchF > 1) {
          part[c] = float2(mx, as_type<float>(kk == INT_MAX ? -1 : kk));
        } else if (kk != INT_MAX) {       /* the chunk is the whole bin */
          buf[taddr(m, (uint)kk)] = mark(j);
        } else {
          const ulong o = out_row(pb + m, P) * nb + j;
          oidx[o] = -1; oval[o] = float2(0.0f); omag[o] = 0.0f;
        }
      }
    }
    threadgroup_barrier(mem_flags::mem_threadgroup | mem_flags::mem_device);
    /* PARTMAX bounds the chunk count only when bins exceed CH, which is also
       the only case that gets here */
    for (uint q = tid; nchF > 1 && q < npm * nb; q += T_TG) {
      const uint m = q / nb, j = q % nb;
      const uint bst = ws + j * bs, e = min(bst + bs, we);
      const uint nch = (e - bst + CH - 1) / CH;
      float bm = t2; int bk = -1;
      for (uint cc = 0; cc < nch; cc++) {
        float2 pp = part[m * NC + j * nchF + cc];
        int pk = as_type<int>(pp.y);
        if (pk >= 0 && pp.x > bm) { bm = pp.x; bk = pk; }
      }
      if (bk >= 0) buf[taddr(m, (uint)bk)] = mark(j);
      else {
        const ulong o = out_row(pb + m, P) * nb + j;
        oidx[o] = -1; oval[o] = float2(0.0f); omag[o] = 0.0f;
      }
    }
  }
  threadgroup_barrier(mem_flags::mem_threadgroup);

  /* the winners' owners write the records */
  for (uint u = 0; u < VPT / RL; u++)
    for (uint r = 0; r < (uint)RL; r++) {
      uint m; uint q = final_pos(tid, u, r, m);
      float x = buf[taddr(m, q)];
      if (x < 0.0f && m < npm) {
        const uint j = unmark(x);
        const ulong o = out_row(pb + m, P) * nb + j;
        const float2 z = v[u * RL + r];
        oidx[o] = (int)q; oval[o] = z; omag[o] = sqrt(mag2(z));
      }
    }
}

/* ================================================== four-step path */

/* w_n^m for m < n, from two small tables: m = mh*H + ml. */
static inline float2 tw4(uint m, uint H, device const float2 *lo, device const float2 *hi) {
  return cmul(hi[m / H], lo[m % H]);
}

kernel void mf_pass1(device const float2 *D     [[buffer(0)]],
                     device const float2 *Tm    [[buffer(1)]],
                     device const float2 *tw    [[buffer(2)]],
                     device float2       *S     [[buffer(3)]],
                     device const float2 *twlo  [[buffer(4)]],
                     device const float2 *twhi  [[buffer(5)]],
                     constant Params     &P     [[buffer(6)]],
                     uint tg  [[threadgroup_position_in_grid]],
                     uint tid [[thread_position_in_threadgroup]]) {
  threadgroup float buf[E_TG];
  float2 v[VPT];
  const uint n = P.n, A = P.A, B = FFT_L, W2 = P.W2;
  const uint rbs = A / FFT_M;                 /* row blocks per pair */
  const uint slot = tg / rbs, rb = tg % rbs;
  const uint2 dt = pair_dt(P.pair0 + slot, P);
  device const float2 *dp = D + (ulong)(P.d0 + dt.x) * n;
  device const float2 *tp = Tm + (ulong)(P.t0 + dt.y) * n;

  for (uint u = 0; u < VPT / RAD0; u++) {
    uint m, i;
    task_mi<RAD0>(tid + u * T_TG, m, i);
    const ulong row = (ulong)(rb * FFT_M + m) * B;
    for (uint r = 0; r < (uint)RAD0; r++) {
      const uint q = i + r * (B / RAD0);
      v[u * RAD0 + r] = cmulc(dp[row + q], tp[row + q]);
    }
  }
  fft_rest(v, buf, tid, tw);

  device float2 *sp = S + (ulong)slot * n;
  for (uint u = 0; u < VPT / RL; u++)
    for (uint r = 0; r < (uint)RL; r++) {
      uint m; const uint k2 = final_pos(tid, u, r, m);
      const uint f1 = rb * FFT_M + m;
      const float2 z = cmul(v[u * RL + r], tw4(f1 * k2, P.H, twlo, twhi));
      sp[(ulong)(k2 / W2) * (A * W2) + f1 * W2 + (k2 % W2)] = z;
    }
}

/* Partial maxima of the bins at either end of a run: (|z|^2, lag, re, im),
   two per run, indexed [slot][run][piece]. */

kernel void mf_pass2(device const float2 *S     [[buffer(0)]],
                     device const float2 *tw    [[buffer(1)]],
                     device float4       *part  [[buffer(2)]],
                     device int          *oidx  [[buffer(3)]],
                     device float2       *oval  [[buffer(4)]],
                     device float        *omag  [[buffer(5)]],
                     constant Params     &P     [[buffer(6)]],
                     uint tg  [[threadgroup_position_in_grid]],
                     uint tid [[thread_position_in_threadgroup]]) {
  threadgroup float buf[E_TG];
  float2 v[VPT];
  const uint n = P.n, A = FFT_L, B = P.B, W2 = FFT_M;
  const uint ntile = B / W2;
  const uint slot = tg / ntile, k2t = tg % ntile;
  const ulong row = out_row(P.pair0 + slot, P);
  device const float2 *sp = S + (ulong)slot * n + (ulong)k2t * (A * W2);

  for (uint u = 0; u < VPT / RAD0; u++) {
    uint m, i;
    task_mi<RAD0>(tid + u * T_TG, m, i);
    for (uint r = 0; r < (uint)RAD0; r++) {
      const uint f1 = i + r * (A / RAD0);
      v[u * RAD0 + r] = sp[f1 * W2 + m];
    }
  }
  fft_rest(v, buf, tid, tw);

  threadgroup_barrier(mem_flags::mem_threadgroup);
  for (uint u = 0; u < VPT / RL; u++)
    for (uint r = 0; r < (uint)RL; r++) {
      uint m; uint q = final_pos(tid, u, r, m);
      buf[taddr(m, q)] = mag2(v[u * RL + r]);      /* = buf[k1*W2 + w] */
    }
  threadgroup_barrier(mem_flags::mem_threadgroup);

  const uint nb = P.nb, bs = P.bs, ws = P.ws, we = P.we;
  const float t2 = P.t2;
  const uint nrun = n / W2;
  device float4 *pp = part + (ulong)slot * nrun * 2;

  /* one thread per run: lags B*k1 + k2t*W2 + [0, W2) */
  for (uint k1 = tid; k1 < A; k1 += T_TG) {
    const uint kb = B * k1 + k2t * W2;
    const uint run = kb / W2;
    const uint kf = max(kb, ws), ke = min(kb + W2, we);
    if (kf >= ke) continue;
    const uint b0 = (kf - ws) / bs, b1 = (ke - 1 - ws) / bs;
    uint cur = b0; float bm = t2; int bk = -1;
    for (uint k = kf; k <= ke; k++) {
      const uint bin = k < ke ? (k - ws) / bs : 0xffffffffu;
      if (bin != cur) {
        /* flush the bin just finished */
        if (cur == b0 || cur == b1) {
          const uint pc = cur == b0 ? 0u : 1u;
          pp[run * 2 + pc].xy = float2(bm, as_type<float>(bk));
          if (bk >= 0) buf[k1 * W2 + (uint)bk - kb] = mark(pc);
        } else if (bk >= 0) {
          buf[k1 * W2 + (uint)bk - kb] = mark(2u + cur);
        } else {
          const ulong o = row * nb + cur;
          oidx[o] = -1; oval[o] = float2(0.0f); omag[o] = 0.0f;
        }
        if (k == ke) break;
        cur = bin; bm = t2; bk = -1;
      }
      const float x = buf[k1 * W2 + (k - kb)];
      if (x > bm) { bm = x; bk = (int)k; }
    }
  }
  threadgroup_barrier(mem_flags::mem_threadgroup);

  for (uint u = 0; u < VPT / RL; u++)
    for (uint r = 0; r < (uint)RL; r++) {
      uint m; const uint k1 = final_pos(tid, u, r, m);
      const float x = buf[taddr(m, k1)];
      if (x < 0.0f) {
        const uint c = unmark(x);
        const uint k = B * k1 + k2t * W2 + m;
        const float2 z = v[u * RL + r];
        if (c < 2u) {
          pp[(k / W2) * 2 + c].zw = z;
        } else {
          const ulong o = row * nb + (c - 2u);
          oidx[o] = (int)k; oval[o] = z; omag[o] = sqrt(mag2(z));
        }
      }
    }
}

/* Which piece of run `run` holds bin j, or -1 if neither.  Mirrors mf_pass2. */
static inline int piece_of(uint run, uint j, constant Params &P) {
  const uint kb = run * P.W2;
  const uint kf = max(kb, P.ws), ke = min(kb + P.W2, P.we);
  if (kf >= ke) return -1;
  const uint b0 = (kf - P.ws) / P.bs, b1 = (ke - 1 - P.ws) / P.bs;
  if (b0 == j) return 0;
  if (b1 == j) return 1;
  return -1;
}

/* Merge pieces, a thread per (pair, bin): for bins spanning few runs. */
kernel void mf_final_thread(device const float4 *part [[buffer(0)]],
                            device int          *oidx [[buffer(1)]],
                            device float2       *oval [[buffer(2)]],
                            device float        *omag [[buffer(3)]],
                            constant Params     &P    [[buffer(4)]],
                            uint gid [[thread_position_in_grid]]) {
  const uint nb = P.nb;
  if (gid >= P.nchunk * nb) return;
  const uint slot = gid / nb, j = gid % nb;
  const uint nrun = P.n / P.W2;
  device const float4 *pp = part + (ulong)slot * nrun * 2;
  const uint s = P.ws + j * P.bs, e = min(s + P.bs, P.we);
  bool found = false;
  float bm = P.t2; int bk = -1; float2 bz = float2(0.0f);
  for (uint run = s / P.W2; run <= (e - 1) / P.W2; run++) {
    const int c = piece_of(run, j, P);
    if (c < 0) continue;
    found = true;
    const float4 q = pp[run * 2 + (uint)c];
    const int k = as_type<int>(q.y);
    if (k >= 0 && q.x > bm) { bm = q.x; bk = k; bz = q.zw; }
  }
  if (!found) return;               /* finished inside one run by pass 2 */
  const ulong o = out_row(P.pair0 + slot, P) * nb + j;
  if (bk >= 0) { oidx[o] = bk; oval[o] = bz; omag[o] = sqrt(bm); }
  else         { oidx[o] = -1; oval[o] = float2(0.0f); omag[o] = 0.0f; }
}

/* Merge pieces, a threadgroup per (pair, bin): for wide bins. */
kernel void mf_final_tg(device const float4 *part [[buffer(0)]],
                        device int          *oidx [[buffer(1)]],
                        device float2       *oval [[buffer(2)]],
                        device float        *omag [[buffer(3)]],
                        constant Params     &P    [[buffer(4)]],
                        uint tg   [[threadgroup_position_in_grid]],
                        uint tid  [[thread_position_in_threadgroup]],
                        uint ntg  [[threads_per_threadgroup]],
                        uint lane [[thread_index_in_simdgroup]],
                        uint sg   [[simdgroup_index_in_threadgroup]],
                        uint nsg  [[simdgroups_per_threadgroup]]) {
  threadgroup float  sm[32];
  threadgroup int    sk[32];
  threadgroup float2 sz[32];
  threadgroup int    sf[32];
  const uint nb = P.nb;
  const uint slot = tg / nb, j = tg % nb;
  const uint nrun = P.n / P.W2;
  device const float4 *pp = part + (ulong)slot * nrun * 2;
  const uint s = P.ws + j * P.bs, e = min(s + P.bs, P.we);
  const uint r0 = s / P.W2, r1 = (e - 1) / P.W2;
  int found = 0;
  float bm = P.t2; int bk = -1; float2 bz = float2(0.0f);
  for (uint run = r0 + tid; run <= r1; run += ntg) {
    const int c = piece_of(run, j, P);
    if (c < 0) continue;
    found = 1;
    const float4 q = pp[run * 2 + (uint)c];
    const int k = as_type<int>(q.y);
    if (k >= 0 && q.x > bm) { bm = q.x; bk = k; bz = q.zw; }
  }
  /* lowest lag among the maxima, which is what a sequential scan keeps */
  const float mx = simd_max(bm);
  const int kk = simd_min((bm == mx && bk >= 0) ? bk : INT_MAX);
  const int anyf = simd_max(found);
  if (bk == kk && bk >= 0) sz[sg] = bz;
  if (lane == 0) { sm[sg] = mx; sk[sg] = kk; sf[sg] = anyf; }
  threadgroup_barrier(mem_flags::mem_threadgroup);
  if (tid == 0) {
    float m = P.t2; int k = INT_MAX; float2 z = float2(0.0f); int f = 0;
    for (uint g = 0; g < nsg; g++) {
      f |= sf[g];
      if (sk[g] != INT_MAX && (sm[g] > m || (sm[g] == m && sk[g] < k))) {
        m = sm[g]; k = sk[g]; z = sz[g];
      }
    }
    if (!f) return;
    const ulong o = out_row(P.pair0 + slot, P) * nb + j;
    if (k != INT_MAX) { oidx[o] = k; oval[o] = z; omag[o] = sqrt(m); }
    else              { oidx[o] = -1; oval[o] = float2(0.0f); omag[o] = 0.0f; }
  }
}
