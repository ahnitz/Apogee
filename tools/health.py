#!/usr/bin/env python3
"""Standing measurements for the iteration loop. See docs/iteration-plan.md.

Prints numbers, asserts nothing. The point is a dashboard that can be run
before and after a change so "better" is a measurement rather than a
feeling. Every entry here exists because something it covers went wrong
once: the descriptor leak presented as a broken driver, the knob census
because 35 of 43 environment switches had no test pinning them, the
run_series split because half that call is host work nobody had timed.

Run:  python tools/health.py
"""
import ast
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent


def h(title):
    print("\n== %s %s" % (title, "=" * max(0, 58 - len(title))))


def census():
    h("size")
    files = (sorted(ROOT.glob("python/matchedfilter/*.py"))
             + sorted(ROOT.glob("src/*.c")) + sorted(ROOT.glob("src/gpu/*.slang")))
    rows = sorted(((len(f.read_text().splitlines()), f) for f in files), reverse=True)
    for n, f in rows[:6]:
        print("  %5d  %s" % (n, f.relative_to(ROOT)))
    print("  %5d  TOTAL" % sum(n for n, _ in rows))

    h("backend duplication")
    def methods(p):
        return set(re.findall(r"def ([a-z_]+)", (ROOT / p).read_text()))
    vk = methods("python/matchedfilter/_vkcompute.py")
    mt = methods("python/matchedfilter/_mtlcompute.py")
    shared = sorted(n for n in vk & mt if not n.startswith("_"))
    print("  methods in BOTH backends: %d  %s" % (len(shared), " ".join(shared)))
    print("  -> each is host orchestration written twice; only the API calls differ")

    h("duplication between the two filter classes")
    src = (ROOT / "python/matchedfilter/__init__.py").read_text()
    tree = ast.parse(src)
    classes = {c.name: {m.name for m in c.body if isinstance(m, ast.FunctionDef)}
               for c in tree.body if isinstance(c, ast.ClassDef)}
    base, sub = classes.get("MatchedFilter", set()), classes.get("HierarchicalFilter", set())
    over = sorted(base & sub)
    print("  HierarchicalFilter overrides %d MatchedFilter methods:" % len(over))
    print("    %s" % " ".join(over))

    h("environment knobs")
    knobs = set()
    for p in list(ROOT.glob("src/*.c")) + list(ROOT.glob("python/matchedfilter/*.py")) \
            + list(ROOT.glob("tools/*.py")):
        knobs |= set(re.findall(r"MF_[A-Z_]{2,}", p.read_text()))
    tests = " ".join(p.read_text() for p in (ROOT / "tests").glob("*.py"))
    docs = " ".join(p.read_text() for p in ROOT.glob("docs/*.md"))
    untested = sorted(k for k in knobs if k not in tests)
    undoc = sorted(k for k in knobs if k not in docs)
    print("  total %d   untested %d   undocumented %d" % (len(knobs), len(untested), len(undoc)))
    print("  every one is a decision a user could be asked to make, and a")
    print("  behaviour no test pins. Untested: %s" % " ".join(untested[:12]))

    h("public API with thin test coverage")
    thin = []
    for c in tree.body:
        if isinstance(c, ast.ClassDef):
            for m in c.body:
                if isinstance(m, ast.FunctionDef) and not m.name.startswith("_"):
                    if tests.count("." + m.name) < 2:
                        thin.append("%s.%s" % (c.name, m.name))
    print("  %s" % (" ".join(thin) if thin else "none"))

    h("magnitude plumbing still in place")
    sites = len(re.findall(r"dtype=np\.float32\)", src))
    hdr = "float magnitude" in (ROOT / "python/matchedfilter/matchedfilter.h").read_text()
    print("  ap_peak carries magnitude: %s; python mag buffers: %d" % (hdr, sites))
    print("  -> allocated, filled by the C, discarded by every caller")


def descriptors():
    h("file descriptors per dropped GPU filter")
    if not sys.platform.startswith("linux") or not os.path.isdir("/proc/self/fd"):
        print("  needs /proc; skipped")
        return
    try:
        import gc
        import numpy as np
        import matchedfilter as mf
    except Exception as e:
        print("  unavailable: %s" % e)
        return
    dev = next((str(d) for d in mf.devices()
                if d.kind == "gpu" and not d.is_software), None)
    if not dev:
        print("  no GPU on this machine")
        return
    n, nd, nt = 1024, 2, 4
    rng = np.random.default_rng(0)
    d = (rng.standard_normal((nd, n)) + 1j * rng.standard_normal((nd, n))).astype(np.complex64)
    t = (rng.standard_normal((nt, n)) + 1j * rng.standard_normal((nt, n))).astype(np.complex64)

    def once():
        f = mf.MatchedFilter(n, nd, nt, device=dev)
        f.set_data(d); f.set_templates(t)
        f.run(binsize=n, threshold=0.0)

    once(); gc.collect()
    base = len(os.listdir("/proc/self/fd"))
    for _ in range(12):
        once()
    gc.collect()
    grew = len(os.listdir("/proc/self/fd")) - base
    print("  12 filters created and dropped: %+d descriptors  (%s)"
          % (grew, "ok" if grew <= 4 else "LEAK -- see the 1024 soft limit"))


def run_series_split():
    h("where GPU run_series spends its time")
    try:
        import numpy as np
        import matchedfilter as mf
    except Exception as e:
        print("  unavailable: %s" % e)
        return
    dev = next((str(d) for d in mf.devices()
                if d.kind == "gpu" and not d.is_software), None)
    if not dev:
        print("  no GPU on this machine")
        return
    N, NT, NB = 4096, 256, 32
    rng = np.random.default_rng(0)
    h_ = (rng.standard_normal((NT, N)) + 1j * rng.standard_normal((NT, N))).astype(np.complex64)
    h_ /= np.linalg.norm(h_, axis=1, keepdims=True)
    step = N // 2
    ns = N + step * NB
    ser = (rng.standard_normal(ns) + 1j * rng.standard_normal(ns)).astype(np.complex64)
    st = (np.arange(NB) * step).astype(np.uintp)
    ws = np.zeros(NB, dtype=np.uintp)
    we = np.full(NB, N // 2, dtype=np.uintp)

    f = mf.MatchedFilter(N, NB, NT, device=dev)
    f.set_templates(h_)
    f.run_series(ser, st, ws, we, binsize=N, threshold=0.0)
    t0 = time.perf_counter()
    for _ in range(5):
        f.run_series(ser, st, ws, we, binsize=N, threshold=0.0)
    whole = (time.perf_counter() - t0) / 5

    t0 = time.perf_counter()                     # the host loop, as written
    for _ in range(5):
        spec = np.zeros((NB, N), dtype=np.complex64)
        buf = np.zeros(N, dtype=np.complex64)
        for b in range(NB):
            lo = int(st[b]); seg = ser[lo:lo + N]
            buf[:] = 0; buf[:seg.size] = seg
            spec[b] = np.fft.fft(buf) / N
    loop = (time.perf_counter() - t0) / 5

    t0 = time.perf_counter()                     # the same thing batched
    for _ in range(5):
        idx = st[:, None].astype(np.int64) + np.arange(N)[None, :]
        blk = np.where(idx < ser.size, ser[np.minimum(idx, ser.size - 1)], 0)
        np.fft.fft(blk, axis=1) / N
    batch = (time.perf_counter() - t0) / 5

    print("  whole call              %8.3f ms" % (whole * 1e3))
    print("  host per-block fft loop %8.3f ms   %.0f%% of the call" % (loop * 1e3, 100 * loop / whole))
    print("  the same, batched       %8.3f ms   %.2fx" % (batch * 1e3, loop / max(batch, 1e-9)))
    print("  -> and it is SERIAL with the device: nothing overlaps the transfer")


def main():
    print("matchedfilter health  --  %s" % subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
        capture_output=True, text=True).stdout.strip())
    census()
    descriptors()
    run_series_split()
    print("\nSee docs/iteration-plan.md for what to do with these.")


if __name__ == "__main__":
    main()
