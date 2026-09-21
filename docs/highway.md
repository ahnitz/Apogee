# The SIMD layer: Google Highway

The kernel is written once, against the `V_*` macros in `src/simd.h`, which
bind to Google Highway. Highway lowers each op to the target's intrinsics, so
the same source serves AVX2, AVX-512, NEON, SVE and the rest.

It is compiled once per lane count -- 4, 8 and 16 -- because Highway's
`FixedTag` cannot exceed the target's native vector. `src/dispatch.c` picks
the widest the CPU supports at run time; `MF_ISA=highway4|highway8|highway16`
forces one.

## What was removed, and what it cost

There used to be three SIMD layers: hand-written AVX-512 and AVX2 intrinsics,
a GCC/Clang vector-extension layer for everything else, and Highway. That is
gone -- `kernel1024.c`, `be_avx512.c`, `transpose16.h`, `simd_portable.h`, the
intrinsic half of `simd.h`, the per-ISA compilation in `setup.py`, the
symbol mangling that kept five back ends from colliding, and the C unit test
that exercised kernels which no longer exist. About 1400 lines.

On AVX2 -- the target that matters, and the only one on most machines --
Highway matches the intrinsics it replaced. On AVX-512 it is 23% behind the
generic intrinsic kernel and 27% behind the specialised one, which had a
tuned 1024 codelet and size-specific paths. That is a deliberate trade: the
specialised AVX-512 path was roughly 500 lines serving hardware that most
runs will not have.

## Measured

Paired in one process, all three at 8 lanes so AVX-512 cannot enter any of
them. Ratio against the hand-written intrinsics, lower is better:

| n | intrinsics | vector-ext | highway |
|---:|---:|---:|---:|
| 1024 | 1.00 | 1.182 | **1.050** |
| 4096 | 1.00 | 1.131 | **1.066** |
| 16384 | 1.00 | 1.146 | **1.089** |
| 65536 | 1.00 | 1.072 | **1.044** |

It beats the vector-extension path at every size and is 4-9% off the
intrinsics.

## The transpose was the whole gap

The first version stored each vector to a scalar array and regathered the
columns. That is correct and reads clearly, and the compiler expanded it into
**960 shuffle instructions** against the intrinsics' 386 -- concentrated in
the stage-A functions, at 192 each against 48.

Writing the same network Highway has primitives for -- `InterleaveLower` /
`InterleaveUpper` on 32-bit lanes, the same on 64-bit lanes via a
`Repartition`, then `ConcatLowerLower` / `ConcatUpperUpper` for the 128-bit
swap -- gives 224 shuffles and 20359 total instructions. Both are *fewer* than
the intrinsic build's 386 and 22441, so whatever remains of the 4-9% is
scheduling rather than work.

Worth noting the same mistake had already been made once, in
`simd_portable.h`, and there it cost nothing measurable. Here it cost most of
the gap. The lesson is not "avoid scalar gathers" but that the cost of one
depends entirely on what surrounds it.

## What the port needed outside the SIMD layer

- **`balanced.c` compiles as C++ as well as C.** `restrict` is mapped to
  `__restrict`, the `void*` plan handles are cast, and `ap_alloc64` returns a
  proxy with a templated conversion operator under C++ so that not one of its
  forty call sites changes. The C build is unaffected and still tested.
- **`allm` follows `AP_W`** instead of assuming 8 or 16.

## What stands between this and replacing the portable back end

Highway's `FixedTag` rejects a width wider than the target's vector, so NEON
wants `AP_W=4` and AVX-512 `AP_W=16`. `codelets.h` is width-neutral already --
one mention of `AP_W` in 8489 lines, in a comment -- so the remaining
obstacles are small and known:

- a transpose network for widths other than 8 (4 and 16)
- the back-end name switch at `balanced.c`'s tail
- `simd.h`'s `#error "AP_W must be 16 or 8"`

The plan's split check (`n1 % w == 0`) already holds for `n1=128, w=4`.

Until those are done this back end is x86-only and exists to be compared
against, not to replace anything.
