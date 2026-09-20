#!/bin/bash
# Corrected benchmark matrix: {AVX-512, AVX2} x {quiet, loaded}.
# Thread counts pinned to 1 as a safety even though MKL is linked sequential and
# FFTW is built without threads.  Wisdom is built once, quietly, and reused in both
# regimes - that is the realistic deployment case (plan once, run many times) and it
# stops FFTW_PATIENT from picking bad plans off contended timings.
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_DYNAMIC=FALSE
set -e
for isa in avx512 avx2; do
  echo "################ $isa / quiet"
  PF_CSV=m_${isa}_quiet.csv PEAKFFT_ISA=$isa taskset -c 4 ./bench/bench4 8
done
for isa in avx512 avx2; do
  echo "################ $isa / loaded (28 memory hogs)"
  PF_CSV=m_${isa}_load.csv ./bench/with_load.sh 28 \
     env PEAKFFT_ISA=$isa taskset -c 4 ./bench/bench4 8
done
