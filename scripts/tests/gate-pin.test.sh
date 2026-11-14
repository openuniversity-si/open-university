#!/usr/bin/env bash
# GX-05 pinned gate (B-09, GA-PG1, D-070): the base tip's tooling judges. Fixture repositories, no network.
# End to end through the real scripts/gate-local: a head that deliberately breaks gate-local (its report-only run
# always passes) and the code (app.txt) is judged red by the pinned base tooling, while its own run says green.
set -uo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
work="$(mktemp -d)"
cleanup() {
  git -C "$work/repo" worktree prune 2>/dev/null || true
  rm -rf "$work"
}
trap cleanup EXIT
# The Python cases keep their own temp dirs and patch their own environment, so they run beside this fixture; their exit
# status is read after it (the fixture's checks are not affected).
PYTHONDONTWRITEBYTECODE=1 python3 "$root/scripts/tests/test_gate_pin.py" >"$work/python.out" 2>&1 &
python_pid=$!
passed=0 failed=0
check() {
  local name="$1"; shift
  if "$@"; then passed=$((passed + 1)); echo "ok   - $name"; else failed=$((failed + 1)); echo "FAIL - $name"; fi
}
export GIT_CONFIG_GLOBAL=/dev/null GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.test GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.test
repo="$work/repo"
mkdir -p "$repo/scripts" "$repo/config" "$repo/contracts/config"
git init -q --bare "$work/origin.git"
git -C "$repo" init -q -b main
git -C "$repo" config commit.gpgsign false
git -C "$repo" remote add origin "$work/origin.git"
# Base tooling: a stand-in for the full gate. It judges the code under test (app.txt of --sha) and records what it saw.
cat >"$repo/scripts/gate-local" <<'STUB'
#!/usr/bin/env bash
prev="" sha=""
for arg in "$@"; do [[ "$prev" != --sha ]] || sha="$arg"; prev="$arg"; done
toolchain=no
[[ ! -x "$(dirname "$0")/../.toolchain/bin/caller-marker" ]] || toolchain=yes
printf 'base-tooling pinned=%s root=%s records=%s lock=%s toolchain=%s args=%s\n' "${OU_GATE_PINNED:-}" \
  "${OU_GATE_RECORD_ROOT:-}" "${GATE_RECORD_DIR:-}" "${GATE_LOCK_FILE:-}" "$toolchain" "$*" >>"$CALLS"
if git -C "$OU_GATE_RECORD_ROOT" show "$sha:app.txt" | grep -q broken; then echo "GATE: FAILED"; exit 1; fi
mkdir -p "$GATE_RECORD_DIR" && printf 'sha=%s\npinned=%s\n' "$sha" "$OU_GATE_PINNED" >"$GATE_RECORD_DIR/$sha.dev.pass"
echo "GATE: PASSED"
STUB
chmod +x "$repo/scripts/gate-local"
printf 'ok\n' >"$repo/app.txt"
git -C "$repo" add -A
git -C "$repo" commit -qm base
base=$(git -C "$repo" rev-parse HEAD)
git -C "$repo" push -q origin main
# Head: the real driver under test, deliberately broken so that its own report-only run always passes, and broken code.
mkdir -p "$repo/scripts/lib"
cp "$root"/scripts/lib/*.py "$root"/scripts/lib/*.json "$root/scripts/lib/gate-budget.sh" "$repo/scripts/lib/"
cp -R "$root/scripts/lib/generated" "$root/scripts/lib/adapters" "$root/scripts/lib/gate-hooks" "$repo/scripts/lib/"
cp -R "$root/config/registry" "$repo/config/"
cp "$root/contracts/config/registry.v1.json" "$repo/contracts/config/"
# The fixture's batch base is its own origin/main; the throwaway repo has no toolchain, so the preflight is off here.
python3 - "$repo/config/registry/gate.json" <<'PY'
import json, sys
path = sys.argv[1]
data = json.load(open(path))
data["properties"]["gate.batch_base_ref"]["default"] = "origin/main"
data["properties"]["gate.preflight_enabled"]["default"] = False
json.dump(data, open(path, "w"))
PY
python3 - "$root/scripts/gate-local" "$repo/scripts/gate-local" <<'PY'
import sys
source, target = sys.argv[1:]
text = open(source).read()
anchor = 'event_pr="$pr"\n'
assert text.count(anchor) == 1
broken = anchor + '[[ $report_only -eq 0 ]] || { echo "GATE: PASSED (report-only)"; exit 0; } # deliberate break\n'
open(target, "w").write(text.replace(anchor, broken))
PY
printf 'broken\n' >"$repo/app.txt"
git -C "$repo" add -A
git -C "$repo" commit -qm 'head: broken gate and code'
head=$(git -C "$repo" rev-parse HEAD)
# The caller's toolchain (gitignored, never in the tool worktree): its marker must be visible from the pinned tooling.
mkdir -p "$repo/.toolchain/bin"
: >"$repo/.toolchain/bin/caller-marker"
chmod +x "$repo/.toolchain/bin/caller-marker"
printf '.toolchain/\n.gate/\n' >>"$repo/.git/info/exclude"
export OU_CONFIG_STORE=file CALLS="$work/calls" GATE_SLOT_DIR="$work/slots" DELIVERY_ENV_FILE="$work/none"
unset OU_GATE_PINNED OU_GATE_RECORD_ROOT OU_GATE_PR_IDENTITY GATE_RECORD_DIR GATE_LOCK_FILE GATE_REPORT_DIR

rc=0; (cd "$work" && "$repo/scripts/gate-local" --dev --sha "$head") >"$work/out" 2>&1 || rc=$?
check "the pinned gate judges the broken head red" test "$rc" = 1
check "gate: pinned to <base sha> is the first line" test "$(head -n 1 "$work/out")" = "gate: pinned to $base"
check "gate_version is printed" grep -qx "gate: version $(git -C "$repo" rev-parse "$base:scripts")" "$work/out"
check "the base tooling ran, pinned, once" test "$(grep -c "^base-tooling pinned=$base " "$CALLS")" = 1
check "the record root is the caller's checkout" grep -q " root=$repo records=$repo/.gate/records lock=$repo/.gate/gate.lock " "$CALLS"
check "the tool worktree uses the caller's toolchain" grep -q " toolchain=yes " "$CALLS"
check "the pinned run gets the caller's arguments" grep -q " args=--dev --sha $head$" "$CALLS"
check "its own report-only run says green" grep -qx "gate: advisory (head tooling, report-only): PASSED; the verdict is the pinned gate: FAILED (exit 1)" "$work/out"
check "no record for the red head" test ! -e "$repo/.gate/records/$head.dev.pass"
tool="$(compgen -G "$work/slots/*/*/$base")"
check "one tool worktree per base sha under gate.slot_dir/gate-pin.dir" test -n "$tool" -a -f "$tool/scripts/gate-local"
check "the tool worktree's .toolchain is a link, not a copy" test -L "$tool/.toolchain"

# A good head on the same base reuses the worktree and its pass is recorded in the caller's checkout.
printf 'ok\n' >"$repo/app.txt"
git -C "$repo" commit -qam 'head: code fixed'
good=$(git -C "$repo" rev-parse HEAD)
touch "$tool/warm"
rc=0; (cd "$work" && "$repo/scripts/gate-local" --dev --sha "$good") >"$work/out2" 2>&1 || rc=$?
check "the pinned gate passes a good head" test "$rc" = 0
check "the tool worktree is reused for the same base" test -f "$tool/warm"
check "the pass is recorded in the caller's checkout, pinned" grep -qx "pinned=$base" "$repo/.gate/records/$good.dev.pass"

# A gate started inside another one (a script test's fixture) inherits a pin hand-off that is not its own: it ignores it,
# pins again and keeps its own record root and PR identity.
rm -f "$CALLS"
rc=0; (cd "$work" && OU_GATE_PINNED="$head" OU_GATE_RECORD_ROOT="$work/elsewhere" OU_GATE_PR_IDENTITY="x	y" \
  "$repo/scripts/gate-local" --dev --sha "$good") >"$work/out4" 2>&1 || rc=$?
check "a leaked hand-off is ignored: the run pins to the base" test "$rc:$(head -n 1 "$work/out4")" = "0:gate: pinned to $base"
check "a leaked record root is not used" grep -q " root=$repo records=$repo/.gate/records " "$CALLS"
check "a pinned run hands no pin variable to the gates it starts" grep -qF 'unset OU_GATE_PINNED OU_GATE_RECORD_ROOT OU_GATE_PR_IDENTITY OU_GATE_VERSION' "$root/scripts/lib/gate-hooks/pin.sh"

# A pin that cannot resolve is a classified driver abort (GX-01), not a pass.
rc=0; (cd "$work" && "$repo/scripts/gate-local" --dev --sha "$(tr '0-9a-f' e <<<"$base")") >"$work/out3" 2>&1 || rc=$?
check "an unknown head is a setup error" test "$rc" -gt 1
check "the abort names the gate pin stage" grep -q "gate pin" "$work/out3"
# The driver itself: the pinned record says which tooling judged it.
# shellcheck disable=SC2016 # the literal driver line, not an expansion
check "a report-only run publishes no events" grep -qF '[[ $report_only -eq 0 ]] || event_pr=""' "$root/scripts/gate-local"

echo "gate-pin tests: $passed passed, $failed failed"
python_rc=0
wait "$python_pid" || python_rc=$?
[[ $python_rc -eq 0 ]] || { echo "---- python ----" >&2; cat "$work/python.out" >&2; }
[[ $failed -eq 0 ]] || { echo "---- out ----" >&2; cat "$work/out" "$work/out2" "$work/out3" "$work/out4" >&2; echo "---- calls ----" >&2; cat "$CALLS" >&2; }
[[ $failed -eq 0 && $python_rc -eq 0 ]]
