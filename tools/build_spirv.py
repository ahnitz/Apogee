"""Compile the GPU kernels to SPIR-V and embed them in the package.

Ahead-of-time, at build time, for two reasons.  The wheel must carry every
backend with no user choice of wheel and no extra package to install, so the
kernels cannot be compiled on the user's machine -- that would put the Slang
toolchain on their critical path.  And compiling once in CI means the shipped
blob is the artefact that was tested, rather than whatever a user's driver
happens to produce.

slangc is a BUILD dependency only.  Nothing at runtime imports slangpy or
touches Slang; the runtime reads these blobs and hands them to Vulkan.

Run:  python tools/build_spirv.py [--slangc PATH]
"""
import argparse
import json
import pathlib
import shutil
import struct
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / "python" / "matchedfilter" / "spirv"
MSL = ROOT / "python" / "matchedfilter" / "metal"

#: Sizes the Tier-B kernel covers.  One source specialised by NLEN rather
#: than a blob per hand-written kernel; 16384 is the ceiling because above it
#: the transform needs more than 1024 threads and must be split across
#: dispatches (Tier C, not yet written).
#:
#: Keep in step with matchedfilter._GPU_SIZES, which is what device="gpu"
#: checks before it builds a plan.
TIER_B = (64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384)

#: The short lengths are not transform sizes a caller asks for -- they are
#: COARSE bands. The hierarchical mode's first pass is the ordinary filter at
#: length `band`, so the same kernel has to exist there. The decomposition
#: generalises down without change: at 512 the workgroup is 32 threads, two
#: exchange levels and an innermost radix of 2.
_COARSE_ONLY = (64, 128, 256, 512)

#: Exchange staging per transform length, in COMPLEX values, measured rather
#: than modelled. The exchange runs R/CH chunks with CH = CAP/WG and each
#: chunk costs two barriers, so too little staging is barrier-bound -- but
#: staging is LDS, and LDS is what caps how many workgroups a CU holds, so
#: too much costs occupancy. The optimum is two chunks almost everywhere.
#:
#: Measured on a Radeon 8060S at threshold 5.5, compute only, against one
#: AVX-512 core (speedup at the chosen value in brackets):
#:
#:     n       4 KB   8 KB  16 KB  32 KB  64 KB
#:     1024    0.81   0.84   0.87   0.84   0.90    -> 4 KB  [60.9x]
#:     2048    1.09   0.93   1.13   1.12   1.19    -> 8 KB  [57.1x]
#:     4096    1.68   1.27   1.13   1.38   1.35    -> 16 KB [44.2x]
#:     8192    8.15   5.16   2.49   2.03   1.83    -> 64 KB [29.2x]
#:     16384  15.92  15.91  12.78   7.56   6.35    -> 64 KB [16.5x]
#:
#: These are THIS device's numbers. 64 KB exceeds what Apple allows a
#: threadgroup, so a Metal build will need its own column -- which is what
#: the per-device tables in docs/plans/gpu-integration.md are for.
#: The largest staging that is portable. Apple allows a threadgroup 32 KB,
#: and several of the fastest entries below exceed it -- so every size whose
#: preferred staging does not fit is ALSO emitted at this cap, and the
#: runtime picks by what the device reports.
#:
#: A software rasteriser will not catch this: llvmpipe reports 32 KB and
#: then runs a 64 KB kernel anyway, so the lavapipe CI path passes where
#: real hardware would fail to create the pipeline.
PORTABLE_CAP = 4096          # complex, = 32 KB

LDS_CAP = {
    64: 512, 128: 512, 256: 512, 512: 512,
    1024: 512, 2048: 1024, 4096: 2048, 8192: 8192, 16384: 8192,
}

#: Metal's own column. The exchange runs R/CH chunks with CH = CAP/WG, and
#: each chunk costs two barriers plus a full R-iteration reader pass of which
#: only CH iterations can land -- so CH = 16 means one chunk, half the
#: barriers, and no wasted address arithmetic. Apple takes that trade and the
#: Radeon does not: the same widening measured, us/pair at 4096 pairs,
#:
#:              Apple M2            Radeon 8060S
#:     n=1024   0.263 -> 0.228      0.0484 -> 0.0555
#:     n=2048   0.599 -> 0.508      0.0499 -> 0.0513
#:     n=4096   1.480 -> 0.736      0.0866 -> 0.1131
#:
#: a 2.01x win at n=4096 on Apple against a 31% loss on the Radeon, which is
#: why this is a separate table and not an edit to the one above. Apple has
#: far less threadgroup memory per core, so a second resident workgroup buys
#: it less than the barriers cost; the Radeon has enough to keep several in
#: flight and would rather have them.
#:
#: Sizes absent here fall back to LDS_CAP. n=4096 at CAP 4096 lands on
#: exactly 32 KB, which is precisely Apple's per-threadgroup limit, so it
#: needs no portable variant.
METAL_CAP = {1024: 1024, 2048: 2048, 4096: 4096}


def metal_cap(n):
    """Staging capacity for the Metal build of this length."""
    return METAL_CAP.get(n, LDS_CAP[n])


KERNEL = ROOT / "src" / "gpu" / "tierb.slang"

#: The tiled coarse kernel, and the only band it is correct for. See the
#: comment at the top of the file: it is a single 16x16 four-step, so the
#: second stage is 16 points, which is right only at band=256.
COARSE_KERNEL = ROOT / "src" / "gpu" / "coarse_tile.slang"
#: Bands that get the tiled coarse kernel, and the registers per lane it
#: uses there. R and BAND/R are the two transform lengths, and the kernel
#: implements 16 and 32 -- so these are the bands where both land on one of
#: those. They are also exactly the bands that need tiling: the untiled
#: kernel's workgroup is BAND/16 threads, which is 16, 32 and 64 here, and
#: is already 128 at band 2048.
COARSE_BANDS = {256: 16, 512: 32, 1024: 32}
#: Production entry points from one source. fusedTierB is the flat/coarse filter.
#: compactPairs turns the coarse results into a survivor list and the X
#: group count an indirect dispatch reads; refineListed is the refine over
#: that list. Together they replace launching one workgroup per pair to have
#: it exit, which was 57% of the hierarchical call at 512x512.
ENTRIES = ("fusedTierB", "compactPairs", "refineListed")
ENTRY = ENTRIES[0]

#: Templates per workgroup on the COARSE path, by band. The tile holds the
#: thread's data slice in registers and reuses it across TILE_T templates,
#: so loads per pair fall as 1/TILE_T -- but the registers come out of
#: occupancy, and whether that is affordable depends on the band.
#:
#: Measured, coarse-only, 512x512 pairs:
#:   band  T=1     T=2     T=4
#:    128  0.735   0.751   0.811   -- no gain; already 87% issue efficient
#:    256  1.118   1.099   1.102   -- flat
#:    512  2.009   1.967   1.686   -- 1.19x, the clear win
#:   1024  3.986   5.893   8.572   -- 2.1x WORSE
#:
#: Band 1024 is the one band already at 100% occupancy (WG=64 is a two-wave
#: group), so every tile register comes straight out of waves. The model
#: predicted exactly this and the measurement confirms it.
COARSE_TILE_T = {128: 2, 256: 2, 512: 4, 1024: 2}
#: Artifact prefix per entry point. Two entries used to be distinguished by
#: `entry == ENTRY`, which silently collides the moment there is a third.
STEMS = {"fusedTierB": "tierb",
         "compactPairs": "compact", "refineListed": "refine"}

_STORAGE_CLASS = {2: "Uniform", 9: "PushConstant", 12: "StorageBuffer"}


def find_slangc(explicit=None):
    """--slangc, then MF_SLANGC, then PATH.

    The env var exists because slangc ships as a tarball rather than a
    package, so it is common for it to live somewhere unpacked rather than
    installed.
    """
    import os
    for candidate in (explicit, os.environ.get("MF_SLANGC"), shutil.which("slangc")):
        if candidate and pathlib.Path(candidate).is_file():
            return str(candidate)
    return None


def reflect(blob):
    """Read the host-side contract back out of the compiled module.

    Parsed from the SPIR-V rather than assumed from the Slang source because
    the two can disagree: `uniform uint ntmpl` in the source becomes a PUSH
    CONSTANT, not a descriptor, and a host written against the source would
    bind a buffer that the module never reads.  Whatever the compiler decided
    is the truth, so ask the artefact.
    """
    words = struct.unpack("<%dI" % (len(blob) // 4), blob)
    if words[0] != 0x07230203:
        raise ValueError("not a SPIR-V module")

    names, sets, bindings, variables = {}, {}, {}, []
    local_size = None
    i = 5
    while i < len(words):
        op, count = words[i] & 0xFFFF, words[i] >> 16
        if count == 0:
            break
        if op == 5:                                   # OpName
            names[words[i + 1]] = struct.pack(
                "<%dI" % (count - 2), *words[i + 2:i + count]
            ).split(b"\0")[0].decode("utf-8", "replace")
        elif op == 71 and count >= 4:                 # OpDecorate
            if words[i + 2] == 33:
                bindings[words[i + 1]] = words[i + 3]
            elif words[i + 2] == 34:
                sets[words[i + 1]] = words[i + 3]
        elif op == 16 and count >= 6 and words[i + 2] == 17:   # LocalSize
            local_size = tuple(words[i + 3:i + 6])
        elif op == 59:                                # OpVariable
            variables.append((words[i + 2], words[i + 3]))
        i += count

    descriptors = []
    push_constant = False
    for vid, storage in variables:
        kind = _STORAGE_CLASS.get(storage)
        if kind == "PushConstant":
            push_constant = True
        elif kind in ("StorageBuffer", "Uniform") and vid in bindings:
            descriptors.append(dict(name=names.get(vid, ""), kind=kind,
                                    set=sets.get(vid, 0), binding=bindings[vid]))
    descriptors.sort(key=lambda d: (d["set"], d["binding"]))
    return dict(local_size=local_size, descriptors=descriptors,
                push_constant=push_constant)


def compile_metal(slangc, n, cap, entry, outdir, suffix="", coarse16=0, ppg=1):
    """Emit Metal Shading Language, and a .metallib when one can be built.

    The MSL is generated anywhere -- it is Slang's own output and needs no
    Apple tooling. Turning it into a .metallib needs `xcrun metal`, which
    exists only on macOS, so that step runs on the macOS wheel builder and
    is skipped elsewhere.

    Shipping the compiled library is the point: the wheel carries kernels,
    not a toolchain, exactly as it does for SPIR-V. The MSL travels too, so
    a device whose .metallib is missing or stale can still be served by
    compiling at run time rather than refusing.
    """
    src = outdir / ("mm_%d_%s%s.slang" % (n, entry, suffix))
    src.write_text("#define NLEN %d\n#define LDS_CAP %d\n#define COARSE16 %d\n"
                   "#define PPG %d\n"
                   % (n, cap, coarse16, ppg) + KERNEL.read_text())
    stem = "%s_%d%s" % (STEMS[entry], n, suffix)
    msl = outdir / (stem + ".metal")
    proc = subprocess.run(
        [slangc, str(src), "-target", "metal", "-entry", entry,
         "-stage", "compute", "-O3", "-o", str(msl)],
        capture_output=True, text=True)
    src.unlink()
    if proc.returncode != 0:
        raise RuntimeError("slangc -target metal failed for n=%d %s:\n%s"
                           % (n, entry, proc.stderr))
    lib = None
    if shutil.which("xcrun"):
        lib = outdir / (stem + ".metallib")
        air = outdir / (stem + ".air")
        for cmd in ([["xcrun", "-sdk", "macosx", "metal", "-c", str(msl),
                      "-o", str(air)],
                     ["xcrun", "-sdk", "macosx", "metallib", str(air),
                      "-o", str(lib)]]):
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print("  metallib step failed (%s); shipping MSL only"
                      % r.stderr.strip().splitlines()[-1:], file=sys.stderr)
                lib = None
                break
        if air.exists():
            air.unlink()
    return msl, lib


def lds_bytes(n, cap):
    """Shared memory the kernel declares: stg[CH * WG * 2] uints.

    Mirrors the kernel's own arithmetic -- WG = n/16, CH = min(cap/WG, 16) --
    so a build cannot claim a size the shader does not actually ask for.
    """
    wg = n // 16
    ch = min(max(cap // wg, 1), 16)
    return ch * wg * 8


def compile_one(slangc, n, outdir, entry=ENTRY, cap=None, suffix="", coarse16=0, ppg=1, tile=1):
    cap = LDS_CAP[n] if cap is None else cap
    src = outdir / ("mf_%d_%s%s.slang" % (n, entry, suffix))
    src.write_text("#define NLEN %d\n#define LDS_CAP %d\n#define COARSE16 %d\n"
                   "#define PPG %d\n#define TILE_T %d\n" % (n, cap, coarse16, ppg, tile) + KERNEL.read_text())
    name = "%s_%d%s.spv" % (STEMS[entry], n, suffix)
    spv = outdir / name
    proc = subprocess.run(
        [slangc, str(src), "-target", "spirv", "-entry", entry,
         "-stage", "compute", "-O3", "-o", str(spv)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("slangc failed for n=%d %s:\n%s"
                           % (n, entry, proc.stderr))
    src.unlink()
    return spv


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--slangc", default=None)
    args = ap.parse_args(argv)

    slangc = find_slangc(args.slangc)
    if slangc is None:
        print("slangc not found; pass --slangc or put it on PATH.\n"
              "It ships in the official Slang release:\n"
              "  https://github.com/shader-slang/slang/releases",
              file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    MSL.mkdir(parents=True, exist_ok=True)
    for band, rpt in COARSE_BANDS.items():
        src = OUT / ("ct_%d.slang" % band)
        src.write_text("#define NBAND %d\n#define RPT %d\n" % (band, rpt)
                       + COARSE_KERNEL.read_text())
        spv = OUT / ("coarse_%d.spv" % band)
        proc = subprocess.run(
            [slangc, str(src), "-target", "spirv", "-entry", "coarseTile",
             "-stage", "compute", "-O3", "-o", str(spv)],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("slangc failed for coarse band=%d:\n%s"
                               % (band, proc.stderr))
        src.unlink()
        # the same kernel in Metal
        csrc = OUT / ("ct_%d_m.slang" % band)
        csrc.write_text("#define NBAND %d\n#define RPT %d\n" % (band, rpt)
                        + COARSE_KERNEL.read_text())
        cm = MSL / ("coarse_%d.metal" % band)
        r = subprocess.run([slangc, str(csrc), "-target", "metal",
                            "-entry", "coarseTile", "-stage", "compute",
                            "-O3", "-o", str(cm)],
                           capture_output=True, text=True)
        csrc.unlink()
        if r.returncode != 0:
            raise RuntimeError("coarse metal band=%d:\n%s" % (band, r.stderr))
        print("  coarse band=%-4d %-16s %5d bytes  tiled R=%d TP=%d (+ %s)"
              % (band, spv.name, spv.stat().st_size, rpt, band // rpt, cm.name))
    manifest = dict(entry=ENTRY, kernel=KERNEL.name, modules={})
    for n in TIER_B:
        if lds_bytes(n, LDS_CAP[n]) > lds_bytes(n, PORTABLE_CAP):
            small = compile_one(slangc, n, OUT, ENTRY, cap=PORTABLE_CAP,
                                suffix="_lds32")
            print("  n=%-6d %-16s %5d bytes  staging %2d KB  portable variant"
                  % (n, small.name, small.stat().st_size,
                     lds_bytes(n, PORTABLE_CAP) // 1024))
        spv = compile_one(slangc, n, OUT)
        info = reflect(spv.read_bytes())
        info["file"] = spv.name
        info["bytes"] = spv.stat().st_size
        # Compaction: gather the pairs that passed the coarse threshold and
        # refine only those. The refine used to launch a workgroup per pair
        # to have it exit -- 57% of the hierarchical call at 512x512 -- and
        # that cost does not shrink with the band because it is not
        # arithmetic. compactPairs is band-independent; refineListed needs
        # the same portable variant the other n-length kernels do.
        comp = compile_one(slangc, n, OUT, "compactPairs")
        cinfo = reflect(comp.read_bytes())
        info["compact"] = dict(file=comp.name,
                               descriptors=len(cinfo["descriptors"]))
        ref = compile_one(slangc, n, OUT, "refineListed")
        rinfo = reflect(ref.read_bytes())
        info["refine"] = dict(file=ref.name,
                              descriptors=len(rinfo["descriptors"]))
        if lds_bytes(n, LDS_CAP[n]) > lds_bytes(n, PORTABLE_CAP):
            rsmall = compile_one(slangc, n, OUT, "refineListed",
                                 cap=PORTABLE_CAP, suffix="_lds32")
            info["refine"]["portable"] = dict(
                file=rsmall.name, lds_bytes=lds_bytes(n, PORTABLE_CAP))
        # Metal, from the same source. Built for every size so a macOS wheel
        # carries the same coverage as a Linux one.
        metal = {}
        mcap = metal_cap(n)

        # The coarse ROLE, at half width. fusedTierB serves
        # the coarse stage as well as their own, and the coarse stage reads
        # the packed cdata/ct0 -- so those two get a SECOND build rather
        # than a changed one, and the flat/refine paths keep full precision.
        for centry in ("fusedTierB",):
            compile_one(slangc, n, OUT, entry=centry, suffix="_c16", coarse16=1)
            # PPG=4: four pairs per workgroup. With the half-width stage that
            # is 8 KB per group, so a CU holds 8 groups x 4 waves = 32 waves
            # against the 16 that one pair per group allowed. Kept as a
            # SEPARATE build so the host can fall back when the pair count
            # is not a multiple of 4 -- a partial group would run pairs off
            # the end of the data buffer.
            for _p in (2, 4):
                compile_one(slangc, n, OUT, entry=centry,
                            suffix="_c16p%d" % _p, coarse16=1, ppg=_p)
            # The TILE is part of kernel IDENTITY. TILE_T is compiled in,
            # so the base variants above MUST be TILE_T=1 and the tiled
            # ones carry their own suffix -- otherwise the host's untiled
            # fallback (taken whenever ntemplates does not divide by the
            # tile, which nt=1, 3 and 5 never do) selects a TILED kernel.
            # That kernel walks TILE_T templates from p0 = gid.x*TILE_T
            # past the end of the bank: traced at band 512 with nt=2, four
            # groups at p0 = 0, 4, 8, 12 left only pairs 0 and 1 reachable.
            #
            # Spelled exactly as the host spells it: "p1" is omitted.
            _t = COARSE_TILE_T.get(n, 1)
            if _t > 1:
                for _p in (1, 2, 4):
                    compile_one(slangc, n, OUT, entry=centry, coarse16=1,
                                ppg=_p, tile=_t,
                                suffix="_c16%st%d"
                                       % ("p%d" % _p if _p > 1 else "", _t))
            compile_metal(slangc, n, mcap, centry, MSL, suffix="_c16", coarse16=1)

        for entry in ENTRIES:
            m, lib = compile_metal(slangc, n, mcap, entry, MSL)
            metal[entry] = dict(msl=m.name,
                                metallib=lib.name if lib else None)
            # Apple caps threadgroup memory at 32 KB, under what the tuned
            # staging asks for at the top sizes. Without a build that fits,
            # those kernels cannot create a pipeline on ANY Mac -- and the
            # refusal arrives as "Compilation failed", naming nothing.
            if lds_bytes(n, mcap) > lds_bytes(n, PORTABLE_CAP):
                sm, slib = compile_metal(slangc, n, PORTABLE_CAP, entry, MSL,
                                         suffix="_lds32")
                metal[entry]["portable"] = dict(
                    msl=sm.name, metallib=slib.name if slib else None,
                    lds_bytes=lds_bytes(n, PORTABLE_CAP))
                print("  n=%-6d %-24s portable Metal variant, staging %d KB"
                      % (n, sm.name, lds_bytes(n, PORTABLE_CAP) // 1024))
        info["metal"] = metal
        # Kept beside, not inside, "metal": the consumers of that key
        # iterate it as entry -> files and a scalar sibling would break
        # them.
        info["metal_lds_cap"] = mcap
        info["metal_lds_bytes"] = lds_bytes(n, mcap)
        info["lds_cap"] = LDS_CAP[n]
        info["lds_bytes"] = lds_bytes(n, LDS_CAP[n])
        if info["lds_bytes"] > lds_bytes(n, PORTABLE_CAP):
            info["portable"] = dict(file="tierb_%d_lds32.spv" % n,
                                    lds_bytes=lds_bytes(n, PORTABLE_CAP))
        manifest["modules"][str(n)] = info
        print("  n=%-6d %-16s %5d bytes  wg=%-4s staging %2d KB  %d descriptors%s"
              % (n, spv.name, info["bytes"], info["local_size"][0],
                 LDS_CAP[n] * 8 // 1024, len(info["descriptors"]),
                 ", push constants" if info["push_constant"] else ""))

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("wrote %s" % (OUT / "manifest.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
