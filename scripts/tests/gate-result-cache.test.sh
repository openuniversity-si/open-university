#!/usr/bin/env bash
# D-065 V6 (M5): the tier-1 cache through the real step_cached wrapper. Hermetic: a temp repo and temp logs.
# OU-DECOUPLE F5 (D-113): the lint and typecheck keys of Open University's web stages left; the wrapper is exercised
# with a content key of its own and the shipped stage graph, which declares no engine stage deterministic.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
lib="$here/../lib"
work="$(mktemp -d)"
trap 'kill "${py_pid:-}" 2>/dev/null || true; rm -rf "$work"' EXIT
# F116: the Python module and the bash block are independent; run them in parallel (measured: neither side dominates).
py_pid=
python3 "$here/test_gate_result_cache.py" >"$work/py.out" 2>&1 &
py_pid=$!
fail() { echo "FAIL $*" >&2; exit 1; }
expect() { [[ "$1" == "$2" ]] || fail "expected [$2] got [$1]: ${3:-}"; }

root="$work/repo"
mkdir -p "$root/products/demo"
git -C "$root" init -q
printf 'export const a = 1;\n' >"$root/products/demo/index.ts"
git -C "$root" add -A

export logs="$work/logs" cache="$work/cache" verbose=0
mkdir -p "$logs"
# shellcheck source=scripts/lib/gate-runner.sh
source "$lib/gate-runner.sh"
GATE_KEY_PARTS="$(python3 "$lib/gate_keys.py" export)"
export GATE_KEY_PARTS

ran="$work/ran"
runs() { if [[ -e "$ran" ]]; then wc -l <"$ran" | tr -d ' '; else echo 0; fi; }
stage() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2]))' "$logs/$1.stage.json" "$2"; }
key_of() { git -C "$root" ls-files -s | sha256sum | cut -d' ' -f1; }
# shellcheck disable=SC2016 # the single quotes keep $1 for the inner bash
check_stage() { step_cached "schema compat" "$root" "$1" bash -c 'echo run >>"$1"' bash "$ran"; }

dev_key="$(key_of)"
check_stage "$dev_key" >/dev/null
expect "$(runs)" 1 "first tier-1 run executes"
expect "$(stage schema_compat cached)" None "a run that executed is not marked cached"

check_stage "$dev_key" >"$work/hit.out"
expect "$(runs)" 1 "a tier-1 hit skips the command"
expect "$(stage schema_compat cached)" True "a hit is recorded as cached"
grep -q '^PASS schema compat (cached: tier-1 result ' "$work/hit.out" || fail "a hit says so in the output"

python3 "$lib/gate_report.py" "$logs" "test-sha" 0
expect "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["cached"])' "$logs/stages.json")" "['schema compat']" "the report lists cached stages"

# An empty key (tiers 2 and 3, or a stage that is not deterministic) always runs the command.
check_stage "" >/dev/null
check_stage "" >/dev/null
expect "$(runs)" 3 "an empty key never uses the cache, even when a tier-1 pass exists"

printf 'export const a = 2;\n' >"$root/products/demo/index.ts"
git -C "$root" add -A
changed_key="$(key_of)"
[[ "$changed_key" != "$dev_key" ]] || fail "a content change must change the key"
check_stage "$changed_key" >/dev/null
expect "$(runs)" 4 "a changed tree runs again"

printf 'export const a = 3;\n' >"$root/products/demo/index.ts"
git -C "$root" add -A
bad_key="$(key_of)"
if step_cached "structure check" "$root" "$bad_key" false >/dev/null 2>&1; then fail "a failing step must fail the gate"; fi
if python3 "$lib/gate_result_cache.py" hit --cache "$cache" --key "$bad_key"; then fail "a failing step must not be stored"; fi

# GS1: the shipped stage graph through gate_stage_key; a corrupt marker reruns the stage.
mode=dev
expect "$(gate_stage_key "script tests" "")" "" "a stage that is not declared deterministic gets no key"
expect "$(mode=full gate_stage_key "script tests" "")" "" "tier 2 and 3 get no stage key"
printf 'export const fresh = true;\n' >"$root/products/demo/index.ts"
git -C "$root" add -A
fresh_key="$(key_of)"
before="$(runs)"
record_run() { echo run >>"$ran"; }
step_cached "schema compat" "$root" "$fresh_key" record_run >/dev/null
step_cached "schema compat" "$root" "$fresh_key" record_run >/dev/null
expect "$(runs)" "$((before + 1))" "the second identical run of a cached stage is a hit"
printf 'garbage' >"$cache/tier1/$fresh_key"
step_cached "schema compat" "$root" "$fresh_key" record_run >/dev/null
expect "$(runs)" "$((before + 2))" "a corrupt marker runs the stage again"
step_cached "schema compat" "$root" "$fresh_key" record_run >/dev/null
expect "$(runs)" "$((before + 2))" "the rerun stores a good marker"

# A pending input-key read must not delay an independent stage's launch. The FIFO is an event barrier; a misplaced
# command substitution would time out before the producer can start. Only a received key permits this assertion.
mkfifo "$work/key-ready"
exec 8<>"$work/key-ready"
gate_stage_key() {
  local received
  IFS= read -r -t 5 received <&8 || return 1
  printf '%s\n' "$received" >"$work/key-received"
  printf '%s' "$received"
}
launch step_cached_by_inputs "deferred input" "$root" "" true
launch bash -c 'printf "%s\n" deferred-key >&8'
join_steps || fail "deferred-key stage and independent producer must finish"
expect "$(cat "$work/key-received")" "deferred-key" "key hashing runs after independent stages can launch"
exec 8>&-

if ! wait "$py_pid"; then cat "$work/py.out" >&2; fail "test_gate_result_cache.py failed"; fi
cat "$work/py.out"
echo "gate-result-cache: shell cases pass"
