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

#: Sizes the Tier-B kernel covers.  One source specialised by NLEN rather
#: than a blob per hand-written kernel; 16384 is the ceiling because above it
#: the transform needs more than 1024 threads and must be split across
#: dispatches (Tier C, not yet written).
#:
#: Keep in step with matchedfilter._GPU_SIZES, which is what device="gpu"
#: checks before it builds a plan.
TIER_B = (1024, 2048, 4096, 8192, 16384)

KERNEL = ROOT / "src" / "gpu" / "tierb.slang"
ENTRY = "fusedTierB"

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


def compile_one(slangc, n, outdir):
    src = outdir / ("mf_%d.slang" % n)
    src.write_text("#define NLEN %d\n" % n + KERNEL.read_text())
    spv = outdir / ("tierb_%d.spv" % n)
    proc = subprocess.run(
        [slangc, str(src), "-target", "spirv", "-entry", ENTRY,
         "-stage", "compute", "-O3", "-o", str(spv)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("slangc failed for n=%d:\n%s" % (n, proc.stderr))
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
    manifest = dict(entry=ENTRY, kernel=KERNEL.name, modules={})
    for n in TIER_B:
        spv = compile_one(slangc, n, OUT)
        info = reflect(spv.read_bytes())
        info["file"] = spv.name
        info["bytes"] = spv.stat().st_size
        manifest["modules"][str(n)] = info
        print("  n=%-6d %-16s %5d bytes  wg=%s  %d descriptors%s"
              % (n, spv.name, info["bytes"], info["local_size"][0],
                 len(info["descriptors"]),
                 ", push constants" if info["push_constant"] else ""))

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("wrote %s" % (OUT / "manifest.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
