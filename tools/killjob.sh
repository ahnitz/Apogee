#!/bin/bash
# Kill background python jobs by pattern, safely.
#
# `pkill -f foo` matches ANY process whose argv contains "foo" -- including the
# shell running the pkill, a heredoc that merely mentions it, and the parent
# shell that passed it as an argument.  That has killed its own run five times
# in this project.  Excluding $$ is not enough (it misses the parent), so match
# on the process NAME instead and only ever kill interpreters.
[ -z "$1" ] && { echo "usage: killjob.sh <pattern>" >&2; exit 2; }
for pid in $(pgrep -f -- "$1"); do
  case "$(ps -o comm= -p "$pid" 2>/dev/null)" in
    python|python3|python3.*) kill "$pid" 2>/dev/null ;;
  esac
done
exit 0
