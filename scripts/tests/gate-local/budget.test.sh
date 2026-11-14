#!/usr/bin/env bash
# The D-064 (f) ceiling (gate-budget.sh): read from the registry, reported per stage, a warning that never fails the gate.
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
# shellcheck source=scripts/lib/gate-budget.sh
source "$root/scripts/lib/gate-budget.sh"
# D-068 / D-069 item 3: the ceiling is gate.ceiling_s (seconds) read from the registry, converted to milliseconds.
# ceiling_of <gate-budget.sh> [env args]: the ceiling a fresh shell computes from that library under that environment.
# shellcheck disable=SC2016 # $1 is the child shell's argument: the library is sourced there, not into this test
ceiling_of() { local lib="$1"; shift; env "$@" bash -c 'source "$1"; printf %s "$GATE_CEILING_MS"' _ "$lib"; }
check "the ceiling is the registry's 180 s in milliseconds" test "$(ceiling_of "$root/scripts/lib/gate-budget.sh" -u GATE_CEILING_MS)" = 180000
check "the ceiling reads the file store whatever the caller's store (F25)" test "$(ceiling_of "$root/scripts/lib/gate-budget.sh" -u GATE_CEILING_MS OU_CONFIG_STORE=no-such-store 2>/dev/null)" = 180000
check "GATE_CEILING_MS still overrides for one run" test "$(ceiling_of "$root/scripts/lib/gate-budget.sh" GATE_CEILING_MS=5000)" = 5000
# The clocks are shell reads of Linux uptime and Bash's epoch; a timestamp never launches Python.
# shellcheck disable=SC2016
check "progress clocks need no interpreter and keep monotonic elapsed time" bash -c '
  GATE_CEILING_MS=1 OU_PYTHON=/must-not-run
  source "$1"
  before=$(gate_now_ms); epoch=$(gate_epoch_ms); after=$(gate_now_ms)
  [[ "$before" =~ ^[0-9]+$ && "$epoch" =~ ^[0-9]+$ && "$after" -ge "$before" && "$epoch" -gt "$after" ]]
' _ "$root/scripts/lib/gate-budget.sh"
mkdir -p "$work/alt/scripts/lib" "$work/alt/config"
cp "$root"/scripts/lib/*.py "$root"/scripts/lib/*.json "$root/scripts/lib/gate-budget.sh" "$work/alt/scripts/lib/"
cp -R "$root/config/registry" "$work/alt/config/"
sed -i 's/"default": 180,/"default": 42,/' "$work/alt/config/registry/gate.json"
check "a registry value of another ceiling changes it (no inline fallback)" test "$(ceiling_of "$work/alt/scripts/lib/gate-budget.sh" -u GATE_CEILING_MS OU_CONFIG_STORE=file)" = 42000
no_budget_warning() { ! grep -q EXCEEDED "$1"; }
mkdir -p "$work/stages"
printf '{"name":"lint","result":"PASS","exit":0,"seconds":70.5}' >"$work/stages/lint.stage.json"
printf '{"name":"integration tests","result":"PASS","exit":0,"seconds":75.25}' >"$work/stages/integration_tests.stage.json"
gate_budget_report 180000 0 "$work/stages" >"$work/budget" 2>&1
check "180s exact is within the D-064 (f) ceiling" grep -q '180.000s (ceiling 180s' "$work/budget"
check "180s exact has no ceiling warning" no_budget_warning "$work/budget"
gate_budget_report 120000 0 "$work/stages" >"$work/budget" 2>&1
check "the old 90s budget no longer warns" no_budget_warning "$work/budget"
rc=0; gate_budget_report 180001 0 "$work/stages" >"$work/budget" 2>&1 || rc=$?
check "over 180s warns" grep -q 'GATE CEILING EXCEEDED' "$work/budget"
check "the warning never fails the gate" test "$rc" = 0
check "the warning lists each stage's time" grep -q '75.250s  integration tests' "$work/budget"
slowest_first() { [[ "$(grep -n 'integration tests' "$1" | cut -d: -f1)" -lt "$(grep -n '70.500s  lint' "$1" | cut -d: -f1)" ]]; }
check "the slowest stage is listed first" slowest_first "$work/budget"
gate_budget_report 180001 1 "$work/nowhere" >"$work/budget" 2>&1
check "nightly also reports an overrun, even without stage files" grep -q "GATE CEILING EXCEEDED" "$work/budget"
check_done
