#!/usr/bin/env python3
"""Build series gather/forward FFTs from the production inverse FFT helpers."""
import pathlib
import subprocess
import tempfile
import build_spirv as build


def build_kernels(compiler, build_module=build):
    """Build every series artifact and return its manifest entries."""
    build = build_module
    entries = {}
    for target, folder, suffix in [('spirv', 'spirv', 'spv'),
                                    ('metal', 'metal', 'metal')]:
        out = build.ROOT / 'python/matchedfilter' / folder / f'pack_coarse.{suffix}'
        subprocess.run([compiler, str(build.ROOT / 'src/gpu/pack_coarse.slang'),
                        '-target', target, '-entry', 'packCoarse', '-stage',
                        'compute', '-O3', '-o', str(out)], check=True)
    source = build.KERNEL.read_text() + '\n' + (
        build.ROOT / 'src/gpu/series_forward.slang').read_text()
    for n in build.TIER_B:
        # A single <=32 KiB variant works on Vulkan and Metal alike.
        cap = min(build.LDS_CAP[n], build.PORTABLE_CAP)
        radix = getattr(build, 'RADIX', {}).get(n, 16)
        defines = (f'#define NLEN {n}\n#define RADIX {radix}\n'
                   f'#define LDS_CAP {cap}\n')
        with tempfile.TemporaryDirectory() as tmp:
            src = pathlib.Path(tmp) / 'forward.slang'
            src.write_text(defines + source)
            for target, folder, suffix in [('spirv', 'spirv', 'spv'),
                                            ('metal', 'metal', 'metal')]:
                out = build.ROOT / 'python/matchedfilter' / folder / f'forward_{n}.{suffix}'
                subprocess.run([compiler, str(src), '-I', str(build.KERNEL.parent), '-target', target,
                                '-entry', 'seriesForward', '-stage', 'compute',
                                '-O3', '-o', str(out)], check=True)
        blob = build.ROOT / 'python/matchedfilter/spirv' / f'forward_{n}.spv'
        info = build.reflect(blob.read_bytes())
        entries[str(n)] = dict(file=blob.name, metal=f'forward_{n}.metal',
                               local_size=info['local_size'], lds_cap=cap)
        print(n, flush=True)
    metal = build.ROOT / 'python/matchedfilter/metal'
    for path in list(metal.glob('forward_*.metal')) + [metal / 'pack_coarse.metal']:
        path.write_text(path.read_text().rstrip() + '\n')
        build.compile_metallib(path)
    return dict(forward=entries, pack_coarse=dict(file='pack_coarse.spv',
                                                 metal='pack_coarse.metal'))


def main():
    # Keep the historical command, but rebuild the complete dependency set.
    return build.main()


if __name__ == '__main__':
    main()
