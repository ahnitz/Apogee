#!/usr/bin/env python3
"""CPU against GPU, each measured against its own ceiling.

Absolute throughput answers "is the GPU worth it". The fraction of peak
answers the more useful question: is the GPU implementation as well
optimised for its hardware as the CPU one is for its?
"""
import math

# --- ceilings -------------------------------------------------------------
# CPU: Zen 5, AVX-512, two FMA units x 16 float32 x 2 flops = 64 flops/cycle.
# Quoted at a sustained 4.5 GHz rather than the 5.19 GHz max boost, which a
# single core holds only briefly and not while anything else runs.
CPU_PEAK = 64 * 4.5e9 / 1e9                 # GFLOP/s, one core
# GPU: measured, not quoted -- a dependent-free FMA chain on the device.
GPU_PEAK = 5427.0                           # GFLOP/s

N, LG = 4096, 12
def flops(pairs):
    return pairs * (5.0 * N * LG + 6.0 * N)

# --- measurements ---------------------------------------------------------
# Both taken on a SHARED box: another user's 32-process job plus this
# repository's own table regeneration. Both numbers are floors, and the CPU
# suffers more because the regeneration is using 30 of 32 cores.
CPU = dict(pairs=512,  ms=2.5163, what="MatchedFilter.run, one thread, AVX3")
GPU = dict(pairs=2048, ms=0.5950, what="fusedBig, Radeon 8060S")
GPU_H = dict(pairs=2048, ms=0.0972, esc=0.031)
CPU_H_SPEEDUP = 6.03                        # pycbc kernel, 9.4% escalating

for tag, m, peak in (("CPU (1 core)", CPU, CPU_PEAK), ("GPU", GPU, GPU_PEAK)):
    g = flops(m["pairs"]) / (m["ms"] * 1e-3) / 1e9
    m["gflops"], m["pct"] = g, 100 * g / peak
    m["us_pair"] = m["ms"] * 1e3 / m["pairs"]

print("Flat matched filter, n=%d\n" % N)
print("%-14s %10s %12s %10s %10s %s"
      % ("", "us/pair", "GFLOP/s", "ceiling", "% of peak", "what"))
for tag, m, peak in (("CPU (1 core)", CPU, CPU_PEAK), ("GPU", GPU, GPU_PEAK)):
    print("%-14s %10.3f %12.0f %10.0f %9.1f%%  %s"
          % (tag, m["us_pair"], m["gflops"], peak, m["pct"], m["what"]))
print("\n  GPU is %.1fx a single CPU core, and %.2fx as close to its own ceiling."
      % (CPU["us_pair"] / GPU["us_pair"], GPU["pct"] / CPU["pct"]))

print("\nHierarchical, same band/n = 256/4096\n")
gh = flops(GPU_H["pairs"]) / (GPU_H["ms"] * 1e-3) / 1e9
ideal = 1.0 / ((256 * 8) / (N * LG) + GPU_H["esc"])
print("%-14s %10s %10s %10s %s" % ("", "speedup", "escal.", "ideal", "% of ideal"))
print("%-14s %9.2fx %9.1f%% %9.2fx %9.0f%%"
      % ("CPU (pycbc)", CPU_H_SPEEDUP, 9.4, 7.37, 100 * CPU_H_SPEEDUP / 7.37))
print("%-14s %9.2fx %9.1f%% %9.2fx %9.0f%%"
      % ("GPU", GPU["ms"] / GPU_H["ms"], 100 * GPU_H["esc"], ideal,
         100 * (GPU["ms"] / GPU_H["ms"]) / ideal))
print("\n  effective %.0f GFLOP/s of avoided work, %.3f us/pair"
      % (gh, GPU_H["ms"] * 1e3 / GPU_H["pairs"]))
