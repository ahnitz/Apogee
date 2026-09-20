#!/bin/bash
# Run a command while N synthetic memory hogs contend for the machine.
#   bench/with_load.sh <workers> <cmd...>
W=${1:-32}; shift
pids=()
for i in $(seq 1 "$W"); do ./bench/loadgen 96 & pids+=($!); done
sleep 3                      # let them reach steady state and evict L3
"$@"
st=$?
kill "${pids[@]}" 2>/dev/null; wait 2>/dev/null
exit $st
