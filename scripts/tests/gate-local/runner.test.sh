#!/usr/bin/env bash
# The runner (gate-runner.sh launch, step, join_steps): failures propagate, timing is monotonic, logs stay grouped, stage records carry started_at.
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
launch step "runner failure" "$work" bash -c 'echo "Error: deliberate regression probe"; exit 23' >>"$work/result"
launch step "runner sibling" "$work" touch "$work/sibling" >>"$work/result"
rc=0; join_steps >>"$work/result" || rc=$?
check "background failure propagates" test "$rc" = 1
check "all siblings finish after a failure" test -f "$work/sibling"
check "millisecond timing on failure" grep -Eq '^FAIL runner failure \([0-9]+\.[0-9]{3}s;' "$logs/runner_failure.log.result"
check "stage exit code is reported" grep -q "; exit 23; log:" "$logs/runner_failure.log.result"
check "full failure log is retained" grep -q 'deliberate regression probe' "$(sed -n 's/.*; log: \(.*\))$/\1/p' "$logs/runner_failure.log.result")"
launch step "runner next batch" "$work" true >>"$work/result"
rc=0; join_steps >>"$work/result" || rc=$?
check "a fresh batch does not inherit stale pids" test "$rc" = 0
dependent() { step "runner prerequisite" "$work" false && step "runner dependent" "$work" touch "$work/dependent"; }
launch dependent >>"$work/result"
rc=0; join_steps >>"$work/result" || rc=$?
check "dependency failure propagates" test "$rc" = 1
check "a failed prerequisite stops its dependent" test ! -f "$work/dependent"
# A backwards wall-clock correction must never produce negative stage durations.
printf '200000\n' >"$work/wall-clock"
# Deliberate stub: invoked only if the runner regresses to wall-clock date calls.
# shellcheck disable=SC2317,SC2329
date() {
  local tick
  read -r tick <"$work/wall-clock"
  printf '%s\n' "$tick"
  printf '%s\n' "$((tick - 100000))" >"$work/wall-clock"
}
step "runner monotonic" "$work" true >>"$work/result"
unset -f date
check "stage timing survives wall-clock corrections" grep -Eq '^PASS runner monotonic \([0-9]+\.[0-9]{3}s\)' "$logs/runner_monotonic.log.result"
verbose=1
for label in A B; do
  # The child shell receives its label as $1.
  # shellcheck disable=SC2016
  launch step "group $label" "$work" bash -c 'echo "BEGIN_$1"; for ((i=0;i<100;i++)); do echo "$1"; done; echo "END_$1"' bash "$label" >>"$work/grouped"
done
join_steps
check "verbose parallel logs remain grouped" python3 -c 'import sys; s=open(sys.argv[1]).read(); assert all("BEGIN_"+k+"\n"+(k+"\n")*100+"END_"+k+"\n" in s for k in "AB")' "$work/grouped"
# GX-38: gate-runner.sh writes started_at (epoch seconds) into every <stage>.stage.json.
step "runner started_at" "$work" true >/dev/null
check "a stage record carries started_at" python3 -c 'import json,sys,time; d=json.load(open(sys.argv[1])); assert 0 < d["started_at"] <= time.time() + 1' "$logs/runner_started_at.stage.json"
# A stage that ends in time ends its watcher without a signal: a signal that lands on a subshell bash has just forked
# runs the caller's EXIT trap there. Only an overrun signals anything (test_gate_gc.py).
signals=()
# A recording stub, invoked by gate-runner.sh's own kill calls (indirectly, as shellcheck cannot see).
# shellcheck disable=SC2317,SC2329
kill() { signals+=("$*"); builtin kill "$@"; }
rc=0; step "runner no signal" "$work" true >/dev/null || rc=$?
unset -f kill
check "a stage that ends in time passes with its record written" test "$rc" = 0
check "a stage that ends in time sends no signal" test "${#signals[@]}" = 0
check "the watcher's FIFO goes with it" test ! -e "$logs/runner_no_signal.log.ended"
check_done
