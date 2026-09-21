# The Google Highway back end

A third SIMD layer behind the same `V_*` macro surface the intrinsic and
vector-extension layers use, so `codelets.h` and `balanced.c` are byte for
byte the same source across all three. Selected with `MF_ISA=highway`.

Built only when Highway's headers are found -- set `HIGHWAY_ROOT` to a
checkout, or install them. Absent otherwise, so nothing in the library
depends on it yet.

## Why it is interesting

The hand-written intrinsics cover AVX-512 and AVX2 and nothing else. The
vector-extension layer covers everything a compiler targets but sits 7-18%
behind, needs `-fno-tree-slp-vectorize` to avoid a 2.3x pessimisation, and
carries its own runtime dispatch and symbol mangling.

Highway would replace all of that: it has NEON, SVE, SVE2, RVV, AltiVec and
WASM targets, its own runtime dispatch (`HWY_DYNAMIC_DISPATCH`), and per-target
compilation (`foreach_target.h`) that subsumes the multiversioning `setup.py`
does by hand. It is also maintained and tuned by people who do only this.

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
