#!/bin/bash
# Batched matrix: {AVX-512, AVX2} x {quiet, loaded}.  Wisdom is import-only here -
# it was built once on a quiet machine.  Planning under contention makes
# FFTW_PATIENT choose off contended timings and poisons every later run.
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_DYNAMIC=FALSE
export AP_WISDOM_RO=1
for isa in avx512 avx2; do
  echo "################ $isa / quiet"
  AP_CSV=bat_${isa}_quiet.csv APOGEE_ISA=$isa taskset -c 4 ./bench/bench_batch 8
done
for isa in avx512 avx2; do
  echo "################ $isa / loaded (28 memory hogs)"
  AP_CSV=bat_${isa}_load.csv ./bench/with_load.sh 28 \
     env APOGEE_ISA=$isa taskset -c 4 ./bench/bench_batch 8
  echo "   (exit $?)"
done
