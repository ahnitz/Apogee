#!/bin/bash
# Replay captures with the current band/taps API; propagate every failure.
# FIXTURES=/path/to/captures PY=python3 BAND=512 REPS=3 bash tools/hier_all.sh
set -euo pipefail
cd "$(dirname "$0")/.."
DIR=${FIXTURES:-work/fixtures}
PY=${PY:-python3}
shopt -s nullglob
files=("$DIR"/hier-*.npz)
if ((${#files[@]} == 0)); then
  echo "No hier-*.npz captures in $DIR" >&2
  exit 1
fi
args=(--no-profile --reps "${REPS:-3}")
[[ -z ${BAND:-} ]] || args+=(--band "$BAND")
[[ -z ${TAPS:-} ]] || args+=(--filter-taps "$TAPS")
[[ -z ${FS:-} ]] || args+=(--first-stage "$FS")
failed=0
for file in "${files[@]}"; do
  OMP_NUM_THREADS=1 "$PY" tools/hier_bench.py --fixture "$file" "${args[@]}" || failed=$((failed+1))
done
printf '%d segments replayed; %d failed\n' "${#files[@]}" "$failed"
((failed == 0))
