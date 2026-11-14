#!/usr/bin/env bash
# The verdict (KD1, GK1, GX-05): the report's exit code ends the gate, no stage waits on the verdict flag, a stage waits only on a dependency it cannot run without.
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
# KD1: the report is the verdict. Its exit code ends the gate (a failed stage whose tests are all known base defects
# passes), and the exit trap never overwrites the report the verdict call wrote.
check "the report's exit code is the verdict" grep -Fq 'then failed=0; else failed=1; fi' "$root/scripts/gate-local"
check "the exit trap does not overwrite a written report" grep -Fq "! -f \"\$logs/stages.json\"" "$root/scripts/gate-local"
# GK1 (D-069 item 12): `failed` is the verdict, never a reason to skip a stage; a known base defect in an earlier stage
# (told apart from a new failure only by the report) must not hide a later stage.
no_failed_guard() { ! grep -Eq "\\\$failed -(eq|ne) 0 *(\]\]|&&)" <(grep -v 'GATE: FAILED' "$root/scripts/gate-local"); }
check "no stage in gate-local waits on the verdict flag" no_failed_guard
# OU-DECOUPLE F5 (D-113): the web install, the DB classification and the browser inventory, the stages others waited
# on, left with Open University; no engine stage blocks the gate.
check "no engine stage is a gate-wide blocker" test "$(grep -c 'gate_block "' "$root/scripts/gate-local")" = 0
check "stages left without a result are recorded as skipped" grep -Fq 'gate_skips.py" remaining' "$root/scripts/gate-local"
# GX-05: event_pr is the PR, empty for a report-only run (no events, no status, no pr.ready).
check "the exit trap reports with the mode and the PR" grep -Fq "\"\$rc\" \"\$mode\" \"\$event_pr\" || rc=1" "$root/scripts/gate-local"
# The two cases on the real helpers: a red script tests stage runs the stage after it; a red dependency skips its
# dependent, named.
scenario() {  # scenario <script-tests rc> <dependency rc>
  local d="$work/scenario-$1-$2" dep_ok=1
  mkdir -p "$d"; logs="$d"; scen_failed=0; gate_blocked=""
  step "script tests" "$work" bash -c "exit $1" >/dev/null || scen_failed=1
  step "dependency" "$work" bash -c "exit $2" >/dev/null || { scen_failed=1; dep_ok=0; }
  if [[ $dep_ok -eq 0 ]]; then gate_skip "dependent" "dependency" >/dev/null; else step "dependent" "$work" true >/dev/null || scen_failed=1; fi
}
scenario 1 0
check "known-defect case: the dependent ran after a red script tests" test -f "$work/scenario-1-0/dependent.stage.json"
check "known-defect case: nothing was recorded as skipped" test -z "$(ls "$work"/scenario-1-0/*.skip.json 2>/dev/null)"
check "known-defect case: the verdict flag is still red" test "$scen_failed" = 1
scenario 0 1
check "dependency case: the dependent did not run" test ! -f "$work/scenario-0-1/dependent.stage.json"
check "dependency case: the verdict flag is red" test "$scen_failed" = 1
check "dependency case: the skip names the dependency" python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["blocked_by"] == "dependency"' "$work/scenario-0-1/dependent.skip.json"
check_done
