#!/usr/bin/env bash
# GK1: a stage skipped by a hard dependency leaves a record; a red independent stage never skips anything.
set -uo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
logs="$work/logs"; mkdir -p "$logs"
verbose=0
# shellcheck source=scripts/lib/gate-runner.sh
source "$root/scripts/lib/gate-runner.sh"
passed=0 failed=0
check() {
  local name="$1"; shift
  if "$@"; then passed=$((passed + 1)); else echo "FAIL gate skip: $name"; failed=$((failed + 1)); fi
}
rc=0; step "independent red" "$work" false >/dev/null || rc=$?
check "the red stage itself fails" test "$rc" = 1
rc=0; gate_unless_blocked "later stage" step "later stage" "$work" touch "$work/later" >/dev/null || rc=$?
check "a red independent stage does not block a later stage" test -f "$work/later"
check "a later stage that ran leaves no skip record" test ! -e "$logs/later_stage.skip.json"
gate_block "install (frozen lockfile)"
gate_block "browser inventory"
check "the first blocker is kept" test "$gate_blocked" = "install (frozen lockfile)"
rc=0; gate_unless_blocked "e2e smoke" step "e2e smoke" "$work" touch "$work/e2e" >"$work/out" || rc=$?
check "a blocked stage does not run" test ! -e "$work/e2e"
check "a skip is not a failure" test "$rc" = 0
check "the skip is printed with its cause" grep -Fq 'SKIP e2e smoke (skipped: install (frozen lockfile) failed)' "$work/out"
check "the skip is recorded apart from stage results" python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["blocked_by"]=="install (frozen lockfile)" and d["name"]=="e2e smoke"' "$logs/e2e_smoke.skip.json"
check "no stage result exists for a skipped stage" test ! -e "$logs/e2e_smoke.stage.json"
mkdir -p "$work/plan"
python3 - "$work/plan" <<'PY'
import json, sys
from pathlib import Path
# OU-DECOUPLE F5 (D-113): the planned stages are the engine's (a dev plan owns no web stage any more).
Path(sys.argv[1], 'plan.json').write_text(json.dumps({'kind': 'scoped', 'stages': ['structure check', 'schema compat', 'script tests']}))
Path(sys.argv[1], 'structure_check.stage.json').write_text(json.dumps({'name': 'structure check', 'result': 'PASS', 'exit': 0, 'seconds': 1}))
PY
out="$(python3 "$root/scripts/lib/gate_skips.py" remaining --logs "$work/plan" --mode dev --blocked-by install)"
check "remaining skips only stages with no result" test "$out" = $'SKIP schema compat (skipped: install failed)\nSKIP script tests (skipped: install failed)'
echo "gate-skip tests: $passed passed, $failed failed"
[[ $failed -eq 0 ]]
