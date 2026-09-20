#!/bin/bash
# Run a command while N synthetic memory hogs contend for the machine.
#   bench/with_load.sh <workers> <cmd...>
#
# Three things here are load-bearing, all learned the hard way:
#
# 1. The hogs are pinned OFF the measurement core.  Unpinned, the scheduler puts
#    some of them on it and the "loaded" numbers are CPU theft rather than memory
#    contention.  PF_LOAD_CPUS is the set they may use; it must exclude whatever
#    core the benchmark itself is pinned to.
# 2. It refuses to start on top of a previous run's hogs.  Two cohorts stacked
#    once and a regime silently ran at 62 workers instead of 28, putting 2^20 at
#    53 ms against 4.6 ms for the same work - a gap big enough to read as a result.
# 3. Cleanup uses `pkill -x`, not `pkill -f`.  A -f pattern of "loadgen" also
#    matches the command line of whatever shell is doing the killing, so the
#    script kills itself and the run dies half-finished.
W=${1:-32}; shift
CPUS=${PF_LOAD_CPUS:-0-3,5-31}

if pgrep -x loadgen >/dev/null 2>&1; then
  echo "with_load.sh: $(pgrep -xc loadgen) loadgen processes already running; refusing" >&2
  exit 1
fi

pids=()
for i in $(seq 1 "$W"); do taskset -c "$CPUS" ./bench/loadgen 96 & pids+=($!); done
sleep 3                      # let them reach steady state and evict L3

# Report what the load actually is, so the log carries it rather than an assumption.
echo "with_load.sh: $(pgrep -xc loadgen) workers on CPUs $CPUS" >&2

"$@"
st=$?
kill "${pids[@]}" 2>/dev/null; wait 2>/dev/null
exit $st
