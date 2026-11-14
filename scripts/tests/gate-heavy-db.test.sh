#!/usr/bin/env bash
# GS1: the cap on heavy database work across parallel gate runs. Hermetic: temp lock directory, no database.
# OU-DECOUPLE F5 (D-113): the stages that held the heavy_db resource (and their runner, gate_resource_run) left with
# Open University; the cap, ou_gate_heavy_db_run in gate-isolation.sh, is driven directly.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
lib="$here/../lib"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
fail() { echo "FAIL $*" >&2; exit 1; }
expect() { [[ "$1" == "$2" ]] || fail "expected [$2] got [$1]: ${3:-}"; }
export GATE_SLOT_DIR="$work/slots" GATE_SLOT_POLL=0.05 tool_root="$here/../.." root="$work"
mkdir -p "$GATE_SLOT_DIR"
# shellcheck source=scripts/lib/gate-isolation.sh
source "$lib/gate-isolation.sh"

# Five separate processes run the same capped command; the log shows how many held a place at once. A job that holds its place
# waits (event-driven, bounded by the registry) until as many jobs as the expected peak (argument 2) have started, so the peak depends on
# the cap under test and never on how fast this machine starts processes (D-069, KF3).
rendezvous_wait="$(python3 "$lib/config.py" get gate.script_test_rendezvous_wait_s)"
[[ "$rendezvous_wait" =~ ^[1-9][0-9]*$ ]] || fail "gate.script_test_rendezvous_wait_s is $rendezvous_wait"
hold="$(python3 "$lib/config.py" get gate.script_test_hold_s)"
peak_of() {
  local slots="$1" want="${2:-$1}" i round="$1" events jobs=$(($1 + 2))
  # Each round has its own slot directory and event log, so rounds can run side by side (F126).
  events="$work/events.$round"
  : >"$events"
  mkdir -p "$work/slots.$round"
  for ((i = 0; i < jobs; i++)); do
    (
      # shellcheck disable=SC2016
      GATE_SLOT_DIR="$work/slots.$round" GATE_HEAVY_DB_SLOTS="$slots" ou_gate_heavy_db_run bash -c '
        events="$1" want="$2" wait_s="$3" hold="$4" poll="$5"
        echo + >>"$events"
        deadline=$((SECONDS + wait_s))
        until [[ $(grep -c "^+" "$events") -ge $want || $SECONDS -ge $deadline ]]; do sleep "$poll"; done
        sleep "$hold"
        echo - >>"$events"' bash "$events" "$want" "$rendezvous_wait" "$hold" "$GATE_SLOT_POLL"
    ) &
  done
  wait
  python3 - "$events" <<'PY'
import sys
live = peak = 0
for sign in open(sys.argv[1]).read().split():
    live += 1 if sign == '+' else -1
    peak = max(peak, live)
print(peak)
PY
}

# The four rounds run at once (own slot directory each); the default round is skipped when it repeats a cap already run.
default="$(python3 "$lib/config.py" get gate.heavy_db_slots)"
[[ "$default" =~ ^[1-9][0-9]*$ ]] || fail "gate.heavy_db_slots is $default"
caps=(2 1 3)
for c in "${caps[@]}"; do [[ "$c" == "$default" ]] && default_dup=1; done
for c in "${caps[@]}" "$default"; do
  if [[ "$c" == "$default" && "${default_dup:-}" == 1 && " ${started:-} " == *" $c "* ]]; then continue; fi
  started="${started:-} $c"
  peak_of "$c" >"$work/peak.$c" &
done
wait
expect "$(cat "$work/peak.2")" 2 "two heavy database slots allow two at once and no more"
expect "$(cat "$work/peak.1")" 1 "one slot serializes the heavy database work"
expect "$(cat "$work/peak.3")" 3 "the cap is the registry value or the override"
# The registry default is a positive integer and is what runs when nothing overrides it.
expect "$(cat "$work/peak.$default")" "$default" "the registry default caps the run"

# A failing command returns its status and frees its place; a bad cap is refused.
if GATE_HEAVY_DB_SLOTS=1 ou_gate_heavy_db_run bash -c 'exit 7'; then fail "failure must propagate"; else expect "$?" 7 "exit status"; fi
GATE_HEAVY_DB_SLOTS=1 ou_gate_heavy_db_run true || fail "the place of a failed command must be free"
if GATE_HEAVY_DB_SLOTS=0 ou_gate_heavy_db_run true 2>/dev/null; then fail "zero slots must be refused"; else expect "$?" 2 "bad cap"; fi
if GATE_HEAVY_DB_SLOTS=x ou_gate_heavy_db_run true 2>/dev/null; then fail "a non-number must be refused"; else expect "$?" 2 "bad cap"; fi

# No engine stage holds the resource in the stage graph (OU-DECOUPLE F5, D-113).
expect "$(python3 "$lib/gate_graph.py" resources "script tests")" ""
echo "gate-heavy-db: ok"
