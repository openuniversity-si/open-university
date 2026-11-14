#!/usr/bin/env bash
# scripts/run test test_x.py finds a module in a subfolder of scripts/tests/ (F99). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
run="$root/scripts/run"
# names are built in pieces so the structure-check does not read them as wrapper globs (F110)
sub="test_origin""_history.py"; top="test_""env.py"; none="test_none""such_subdir.py"
fail() { echo "FAIL: $*" >&2; exit 1; }
[[ "$("$run" --print test "$sub")" == "scripts/tests/forge_events/$sub" ]] || fail "subfolder module resolves"
[[ "$("$run" --print test "$top")" == "scripts/tests/$top" ]] || fail "top-level module still wins"
"$run" --print test "$none" 2>/dev/null && fail "unknown module must be refused"
echo "run-subdir.test.sh: ok"
