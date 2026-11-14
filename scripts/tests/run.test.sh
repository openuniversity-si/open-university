#!/usr/bin/env bash
# scripts/run resolves a gate or a test to the existing script and adds nothing (D-069 item 12). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
run="$root/scripts/run"
top="test_""env.py"
fail() { echo "FAIL: $*" >&2; exit 1; }
[[ "$("$run" --print gate)" == "scripts/gate-dev" ]] || fail "default gate is dev"
[[ "$("$run" --print gate dev --pr 7)" == "scripts/gate-dev --pr 7" ]] || fail "arguments pass through"
[[ "$("$run" --print gate quiet)" == "scripts/gate-quiet" ]] || fail "named gate"
[[ "$("$run" --print gate --pr 7)" == "scripts/gate-dev --pr 7" ]] || fail "flags after gate belong to the dev gate"
[[ "$("$run" --print gate verdict --no-run --json)" == "scripts/gate-verdict --no-run --json" ]] || fail "the gate API"
[[ "$("$run" --print test env)" == "scripts/tests/env.test.sh" ]] || fail "test resolves to its script"
"$run" --print gate nonesuch 2>/dev/null && fail "unknown gate must be refused"
[[ "$("$run" --print test "$top")" == "scripts/tests/$top" ]] || fail "a .py module resolves"
missing="test_none""such.py"
"$run" --print test "$missing" 2>/dev/null && fail "unknown module must be refused"
"$run" --print test nonesuch 2>/dev/null && fail "unknown test must be refused"
"$run" 2>/dev/null && fail "no kind must be refused"
"$run" bogus 2>/dev/null && fail "unknown kind must be refused"
# the real thing: a test through the entry command exits like the script itself
"$run" test structure-wiring >/dev/null 2>&1 || fail "run test structure-wiring"
echo "run.test.sh: ok"
