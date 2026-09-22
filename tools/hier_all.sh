#!/bin/bash
# Replay every captured pycbc segment and total the result.  This is the
# number to move: the operating point that misses no triggers.
#   MF_GATE_MARGIN=0.94 bash tools/hier_all.sh
#   BAND=512 bash tools/hier_all.sh
cd "$(dirname "$0")/.."
DIR=${FIXTURES:-/home/ahnitz/projects/claude/searchdev/work/fixtures}
PY=${PY:-/tmp/env-hwy/bin/python}
tru=0; miss=0; ms=0; sp=0; nf=0; tr=0; ok=1
for F in $DIR/hier-*.npz; do
  out=$(OMP_NUM_THREADS=1 $PY tools/hier_bench.py --fixture $F --no-profile --reps ${REPS:-3} ${BAND:+--band $BAND} 2>&1)
  echo "$out"|grep -q "proof: all" || ok=0
  t=$(echo "$out"|grep -oP "the flat filter finds\s+\K[0-9]+"); m=$(echo "$out"|grep -oP "flat filter: \K[0-9]+")
  v=$(echo "$out"|grep -oP 'hierarchical\s+\K[0-9.]+'); x=$(echo "$out"|grep -oP 'hierarchical.*\s\K[0-9.]+(?=x)')
  r=$(echo "$out"|grep -oP 'triggered\s+\K[0-9.]+')
  tru=$((tru+t)); miss=$((miss+m)); nf=$((nf+1))
  ms=$(echo "$ms+$v"|bc); sp=$(echo "$sp+$x"|bc); tr=$(echo "$tr+$r"|bc)
done
printf "%d segments  band=%s  gate=%s  missed %d/%d (%s)  triggered %s%%  %s ms/seg  %sx\n" \
  $nf "${BAND:-auto}" "${MF_GATE_MARGIN:-1.00}" $miss $tru "$(echo "scale=5;$miss/$tru"|bc)" \
  "$(echo "scale=2;$tr/$nf"|bc)" "$(echo "scale=2;$ms/$nf"|bc)" "$(echo "scale=2;$sp/$nf"|bc)"
