#!/usr/bin/env python3
"""Inventory native CPU assembly and RADV shader statistics (developer tool).

Capture GPU assembly:
  MESA_SHADER_CACHE_DISABLE=1 RADV_DEBUG=shaderstats,asm \
    python tools/audit_kernel_binaries.py --capture-gpu 2>gpu.asm
Then write a machine-readable review:
  python tools/audit_kernel_binaries.py --gpu-log gpu.asm --output audit.json

Counts are static, not execution profiles. Stack operands are not a proof of
register spilling; RADV's scratch statistics are driver-specific resource data.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def cpu_inventory(library):
    text = subprocess.check_output(['objdump', '-d', '-C', '--no-show-raw-insn',
                                    str(library)], text=True)
    rows = []
    for match in re.finditer(r'^([0-9a-f]+) <([^\n]+)>:\n(.*?)(?=^[0-9a-f]+ <|\Z)',
                             text, re.M | re.S):
        name = match[2]
        if not name.startswith('ap::N_'):
            continue
        instructions = re.findall(r'^\s*[0-9a-f]+:\s+([\w.]+)\s*(.*)$', match[3], re.M)
        ops = Counter(op for op, _ in instructions)
        rows.append(dict(symbol=name, instructions=len(instructions),
                         stack_operands=sum('%rsp' in args or '%rbp' in args
                                            for _, args in instructions),
                         fma=sum(count for op, count in ops.items()
                                 if re.match(r'v(?:fm|fnm)', op)),
                         branches=sum(count for op, count in ops.items()
                                      if op.startswith('j')), opcodes=dict(ops)))
    return rows


def gpu_inventory(text, folder):
    import build_spirv
    rows = []
    for part in text.split('AUDIT_KERNEL ')[1:]:
        filename = part.splitlines()[0]
        stats = {key: int(value) for key, value in
                 re.findall(r'^([\w -]+): (\d+)\s*$', part, re.M)}
        if not stats:
            continue
        blob = (folder / filename).read_bytes()
        ops = Counter(re.findall(r'^\t([a-z][\w.]*)\s', part, re.M))
        rows.append(dict(file=filename, sha256=hashlib.sha256(blob).hexdigest(),
                         local_size=build_spirv.reflect(blob)['local_size'],
                         stats=stats, opcodes=dict(ops)))
    captured = {row['file'] for row in rows}
    for filename, reason in re.findall(r'^AUDIT_SKIP (\S+) (.+)$', text, re.M):
        if filename in captured:
            continue
        blob = (folder / filename).read_bytes()
        rows.append(dict(file=filename, sha256=hashlib.sha256(blob).hexdigest(),
                         local_size=build_spirv.reflect(blob)['local_size'],
                         skipped=reason, stats={}, opcodes={}))
        captured.add(filename)
    return rows


def capture_gpu():
    import build_spirv
    from matchedfilter import _vkcompute as v
    context = v.Context(0)
    try:
        for path in sorted(v._SPIRV.glob('*.spv')):
            info = build_spirv.reflect(path.read_bytes())
            if info['local_size'][0] > context.max_invocations:
                print('AUDIT_SKIP %s exceeds workgroup limit' % path.name,
                      file=sys.stderr, flush=True)
                continue
            push_bytes = (8 if path.stem.startswith('coarse_') else
                          12 if path.stem.startswith('compact_') else
                          16 if path.stem == 'pack_coarse' else
                          4 if path.stem.startswith('forward_') else 28)
            print('AUDIT_KERNEL ' + path.name, file=sys.stderr, flush=True)
            context._build_pipeline(path.name, path.name,
                                    len(info['descriptors']), push_bytes)
    finally:
        context.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-gpu', action='store_true')
    parser.add_argument('--library', type=Path)
    parser.add_argument('--gpu-log', type=Path)
    parser.add_argument('--output', type=Path, default=Path('kernel-audit.json'))
    args = parser.parse_args()
    if args.capture_gpu:
        capture_gpu()
        return
    import matchedfilter
    from matchedfilter import _core
    library = args.library or Path(_core.__file__)
    result = dict(cpu_library=library.name,
                  cpu_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
                  cpu=cpu_inventory(library))
    if args.gpu_log:
        result['gpu'] = gpu_inventory(args.gpu_log.read_text(),
                                     Path(matchedfilter.__file__).parent / 'spirv')
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('%d CPU functions; %d GPU variants' %
          (len(result['cpu']), len(result.get('gpu', []))))


if __name__ == '__main__':
    main()
