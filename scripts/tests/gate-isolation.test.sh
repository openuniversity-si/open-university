#!/usr/bin/env bash
# shellcheck disable=SC2016  # single-quoted snippets run in child shells or are matched literally
# D-064 (b): per-worktree test database, global gate semaphore and free e2e port. Offline: the
# database part uses a stub psql; the semaphore uses a private slot directory.
set -uo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
work="$(mktemp -d)"
cleanup() { jobs -p | xargs -r kill 2>/dev/null; rm -rf "$work"; }
trap cleanup EXIT
# shellcheck source=scripts/lib/gate-isolation.sh
source "$root/scripts/lib/gate-isolation.sh"
unset OU_GATE_SLOT
matches() { [[ "$1" =~ $2 ]]; }
passed=0 failed=0
check() {
  local name="$1"; shift
  if "$@"; then passed=$((passed + 1)); else echo "FAIL gate isolation: $name"; failed=$((failed + 1)); fi
}

# 1. Database name per checkout.
a="$(ou_test_db_name /workspace/one)"; b="$(ou_test_db_name /workspace/two)"
check "name is stable for one path" test "$a" = "$(ou_test_db_name /workspace/one)"
check "two worktrees get two databases" test "$a" != "$b"
check "name shape tower_test_<10 hex>" matches "$a" '^tower_test_[0-9a-f]{10}$'
check "never collides with integration databases" test "${a#tower_test_g}" = "$a"
url="$(env -u TEST_DATABASE_URL -u APP_DATABASE_URL_CONTAINER_UNPOOLED bash -c 'source "$1/scripts/cloud/env.sh"; printf %s "$TEST_DATABASE_URL"' _ "$root")"
check "env.sh derives the URL from this checkout" test "${url##*/}" = "$(ou_test_db_name "$root")"
check "env.sh keeps the local server" test "${url%/*}" = postgresql://postgres@127.0.0.1:54322
kept="$(TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:54322/explicit bash -c 'source "$1/scripts/cloud/env.sh"; printf %s "$TEST_DATABASE_URL"' _ "$root")"
check "an explicit TEST_DATABASE_URL still wins" test "$kept" = postgresql://postgres@127.0.0.1:54322/explicit

# 2. Creation on demand (stub psql records statements; the database "exists" after create).
mkdir -p "$work/bin"
cat >"$work/bin/psql" <<'STUB'
#!/usr/bin/env bash
printf '%s|%s\n' "${1##*/}" "$3" >>"$PSQL_LOG"
case "$3" in
  select*) [[ -e "$PSQL_STATE" ]] && echo 1 ;;
  create*) : >"$PSQL_STATE" ;;
esac
exit 0
STUB
chmod +x "$work/bin/psql"
export PSQL_LOG="$work/psql.log" PSQL_STATE="$work/created"
PATH="$work/bin:$PATH" ou_test_db_ensure "postgresql://postgres@127.0.0.1:54322/$a"; rc=$?
check "ensure creates a missing database" test "$rc" = 0
check "creation goes through the maintenance database" grep -q "^postgres|create database \"$a\"$" "$PSQL_LOG"
: >"$PSQL_LOG"
PATH="$work/bin:$PATH" ou_test_db_ensure "postgresql://postgres@127.0.0.1:54322/$a"
check "ensure is idempotent" test "$(grep -c create "$PSQL_LOG")" = 0
rc=0; PATH="$work/bin:$PATH" ou_test_db_ensure "postgresql://u@db.example.com:5432/$a" 2>/dev/null || rc=$?
check "ensure refuses a non-local server" test "$rc" = 2
rc=0; PATH="$work/bin:$PATH" ou_test_db_ensure "postgresql://u@127.0.0.1:54322/x;drop" 2>/dev/null || rc=$?
check "ensure refuses an unsafe database name" test "$rc" = 2

# 3. Global semaphore: GATE_SLOTS holders at once, the next one waits for a release.
export GATE_SLOT_DIR="$work/slots" GATE_SLOTS=3
mkdir -p "$GATE_SLOT_DIR"
holder() { # $1 = name; holds a slot until $work/release-$1 exists
  bash -c 'source "$1"; unset OU_GATE_SLOT; ou_gate_slot_acquire 2>/dev/null || exit 1
    echo "$OU_GATE_SLOT" >"$2/got-$3"; while [[ ! -e "$2/release-$3" ]]; do sleep 0.05; done' _ \
    "$root/scripts/lib/gate-isolation.sh" "$work" "$1" &
}
wait_for() { local i; for ((i = 0; i < 100; i++)); do [[ -e "$1" ]] && return 0; sleep 0.05; done; return 1; }
holder 1; holder 2; holder 3
all_three() { wait_for "$work/got-1" && wait_for "$work/got-2" && wait_for "$work/got-3"; }
check "three gates get slots" all_three
check "the three slots are distinct" test "$(sort -u "$work"/got-* | wc -l)" = 3
holder 4
sleep 0.6
check "a fourth gate waits while three run" test ! -e "$work/got-4"
: >"$work/release-2"
check "the fourth gate starts when one finishes" wait_for "$work/got-4"
check "it takes the released slot" test "$(cat "$work/got-4")" = "$(cat "$work/got-2")"
: >"$work/release-1"; : >"$work/release-3"; : >"$work/release-4"; wait
OU_GATE_SLOT=2; ou_gate_slot_acquire; rc=$?
check "a nested gate reuses its parent's slot" test "$rc:$OU_GATE_SLOT" = "0:2"
unset OU_GATE_SLOT
rc=0; GATE_SLOTS=0 ou_gate_slot_acquire 2>/dev/null || rc=$?
check "GATE_SLOTS must be positive" test "$rc" = 2
check "gate-local takes a slot for the whole run" grep -q '^ou_gate_slot_acquire || driver_abort "gate slot" ' "$root/scripts/gate-local"

# D-064 (f): one fixed --sha checkout per slot keeps path-keyed lint/tsc caches warm across worktrees.
rc=0; ( unset OU_GATE_SLOT OU_GATE_SLOT_OWNER; ou_gate_checkout_dir >/dev/null ) || rc=$?
check "no slot, no fixed checkout path" test "$rc" = 1
got="$( OU_GATE_SLOT=3 OU_GATE_SLOT_OWNER=$$ GATE_CHECKOUT_ROOT="$work/co" ou_gate_checkout_dir )"
check "the slot owner gets its slot's checkout path" test "$got" = "$work/co/slot3"
if [[ "$(id -u)" -eq 0 ]]; then
  got="$( unset GATE_CHECKOUT_ROOT; OU_GATE_SLOT=1 OU_GATE_SLOT_OWNER=$$ ou_gate_checkout_dir )"
  check "uid 0 without GATE_CHECKOUT_ROOT slots outside a private home (D-165)" test "$got" = "$(ou_config_value cloud.root_gate_checkout_root)/slot1"
fi
rc=0; ( OU_GATE_SLOT=3 OU_GATE_SLOT_OWNER=1 ou_gate_checkout_dir >/dev/null ) || rc=$?
check "a nested gate (inherited slot) gets no fixed path" test "$rc" = 1
check "gate-local uses the slot checkout path" grep -qF 'wt="$(ou_gate_checkout_dir)" || wt="$record_dir/checkout"' "$root/scripts/gate-local"

# 5. D-068 / D-069 item 3: slot count, directory and poll come from the registry; the env overrides win for one run.
check "gate.slots is an override, 0 means derived from the vCPUs" test "$(ou_config_value gate.slots)" = 0
slots_for() { env -u GATE_SLOTS GATE_VCPUS="$1" bash -c 'source "$1/scripts/lib/gate-isolation.sh"; ou_gate_slot_count' _ "$root"; }
check "one vCPU still gets one slot" test "$(slots_for 1)" = 1
two=$((1 + 1))
# D-076 (GATE-FAST) made the derived count max(1, floor(vCPUs x gate.slots_per_vcpu)); the expectation reads that key,
# so a registry change never leaves this test stale again (it pinned 4 -> 1 and 8 -> 2 until GATE-TRAIN-SERVICES).
per_vcpu="$(ou_config_value gate.slots_per_vcpu)"
derived() { "${OU_PYTHON:-python3}" -c 'import sys; cpus, per = sys.argv[1:]; print(max(1, int(int(cpus) * float(per))))' "$1" "$per_vcpu"; }
check "a small container gets its vCPUs times gate.slots_per_vcpu" test "$(slots_for $((two + two)))" = "$(derived $((two + two)))"
check "eight vCPUs get their vCPUs times gate.slots_per_vcpu" test "$(slots_for $((two * two * two)))" = "$(derived $((two * two * two)))"
check "more vCPUs never get fewer slots" test "$(slots_for $((two * two * two)))" -ge "$(slots_for $((two + two)))"
check "GATE_SLOTS wins over the vCPUs" test "$(GATE_SLOTS="$two" GATE_VCPUS=1 bash -c 'source "$1/scripts/lib/gate-isolation.sh"; ou_gate_slot_count' _ "$root")" = "$two"
check "the registry holds the /tmp slot directory" test "$(ou_config_value gate.slot_dir)" = /tmp
check "a waiter blocks on the slot locks, never an interval (F8b)" bash -c '! grep -nE "(^|[;&|(\s])sleep\s" "$1"' _ "$root/scripts/lib/gate-isolation.sh"
mkdir -p "$work/alt/scripts/lib" "$work/alt/scripts/cloud" "$work/alt/config" "$work/altslots"
cp "$root"/scripts/lib/*.py "$root"/scripts/lib/*.json "$root/scripts/lib/gate-isolation.sh" "$work/alt/scripts/lib/"
cp "$root/scripts/cloud/test-db.sh" "$work/alt/scripts/cloud/"
cp -R "$root/config/registry" "$work/alt/config/"
cp -R "$root/contracts" "$work/alt/"
sed -i -e '/"gate.slots": {/,/"default"/ s/"default": 0,/"default": 2,/' -e "s|\"default\": \"/tmp\"|\"default\": \"$work/altslots\"|" "$work/alt/config/registry/gate.json"
alt_slots() {
  env -u GATE_SLOTS -u GATE_SLOT_DIR -u OU_GATE_SLOT "$@" bash -c \
    'source "$1/scripts/lib/gate-isolation.sh"; ou_gate_slot_acquire 2>/dev/null || exit 1; printf "%s %s" "$OU_GATE_SLOTS" "$OU_GATE_SLOT"' _ "$work/alt"
}
check "a registry of two slots in its own directory drives the semaphore" test "$(alt_slots)" = "2 1"
check "the lock files sit in the registry's directory" test -e "$work/altslots/tower-gate.slot1"
check "GATE_SLOTS still overrides the registry for one run" test "$(alt_slots GATE_SLOTS=4)" = "4 1"

echo "gate isolation: $passed passed, $failed failed"
[[ $failed -eq 0 ]]
