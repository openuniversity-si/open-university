#!/usr/bin/env bash
# HD1: the loopback REST fake starts by readiness probe, never a fixed count of looks, so a loaded machine only delays it.
set -uo pipefail
src="$(cd "$(dirname "$0")/../.." && pwd)"
work="$(mktemp -d)"
server_pid="" load_pids=()
cleanup() {
  for pid in "${load_pids[@]}" $server_pid; do kill "$pid" 2>/dev/null || true; done
  rm -rf "$work"
}
trap cleanup EXIT
passed=0 failed=0
check() {
  local name="$1"; shift
  if "$@"; then passed=$((passed + 1)); echo "ok   - $name"; else failed=$((failed + 1)); echo "FAIL - $name"; fi
}
# shellcheck source=scripts/tests/rest-fake-start.sh
source "$src/scripts/tests/rest-fake-start.sh"
mkdir -p "$work/api"
printf '{"state": "open"}\n' >"$work/api/pull.json"

# Artificial CPU load: two busy loops per core, so the fake's interpreter start competes for every core.
spin() { while :; do :; done; }
for _ in $(seq "$(nproc)"); do spin & load_pids+=($!); spin & load_pids+=($!); done # host-ok: load size only, never an expected value
rc=0; rest_fake_start "$work/api" "$work/port" 2>"$work/err" || rc=$?
check "fake becomes ready under CPU load" test "$rc" = 0
check "probe returns the listening port" test "$rest_fake_port" = "$(cat "$work/port")"
# The probe itself is an HTTP request: ready means the fake answered one under the load.
for pid in "${load_pids[@]}" "$server_pid"; do kill "$pid" 2>/dev/null; done; load_pids=()

# A fake that exits before it is ready fails at once, not after the readiness limit.
started=$SECONDS; rc=0
rest_fake_start "$work/missing/dir" "$work/missing/port" 2>"$work/err" || rc=$?
check "an exited fake is reported" test "$rc" = 1
check "with the documented message" grep -q "rest fake did not start" "$work/err"
limit=$(python3 "$src/scripts/lib/config.py" get delivery.test_fake_ready_max_s)
check "an exited fake fails before the readiness limit" test $((SECONDS - started)) -lt "$limit"

# Class guard: no script suite starts the fake outside the helper (a fixed wait would return).
stray=$(grep -l 'rest_fake.py" --dir' "$src"/scripts/tests/*.sh "$src"/scripts/tests/*/*.sh | grep -v -e '/rest-fake-start.sh$' -e '/rest-fake-ready.test.sh$' || true)
check "every shell suite starts the fake through rest-fake-start.sh" test -z "$stray"
echo "rest-fake-ready tests: $passed passed, $failed failed"
[[ $failed -eq 0 ]]
