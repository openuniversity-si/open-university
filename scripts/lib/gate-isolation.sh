#!/usr/bin/env bash
# D-064 (b): gate isolation per worktree. Sourced by scripts/gate-local and scripts/gate-check.
# - ou_test_db_name, ou_test_db_ensure: the checkout's local test database, from scripts/cloud/test-db.sh (D-322).
# - ou_gate_slot_acquire: a global semaphore of GATE_SLOTS (default 3) concurrent gates.
# - ou_gate_checkout_dir: the fixed per-slot path of a --pr/--sha checkout (warm lint/tsc caches).
# shellcheck shell=bash

# shellcheck source=scripts/cloud/test-db.sh
source "$(dirname "${BASH_SOURCE[0]}")/../cloud/test-db.sh"

# ou_config_value NAME: the registry value of NAME (config/registry, D-068), printed bare. config.py prints JSON, so a
# string comes back quoted; this strips the quotes, which is right for the paths and numbers the gate reads.
_ou_config_py="$(dirname "${BASH_SOURCE[0]}")/config.py"
ou_config_value() {
  local value
  value="$("${OU_PYTHON:-python3}" "$_ou_config_py" get "$1")" || return
  value="${value#\"}"
  printf '%s\n' "${value%\"}"
}

# Holds one of the gate.slots lock files (gate.slot_dir/tower-gate.slot<N>, D-068) on a descriptor that lives
# until the calling shell exits. Sets OU_GATE_SLOT to the slot number and OU_GATE_SLOTS to the count. The
# descriptor is opened read-only without O_CREAT, like ou_flock in env.sh, so a slot file left by another uid still works.
# The count is GATE_SLOTS, else the gate.slots override (> 0), else max(1, floor(vCPUs x gate.slots_per_vcpu)) (GX-03).
ou_gate_slot_count() {
  local override
  [[ -z "${GATE_SLOTS:-}" ]] || { printf '%s\n' "$GATE_SLOTS"; return 0; }
  override="$(ou_config_value gate.slots)" || return
  if [[ "$override" =~ ^[1-9][0-9]*$ ]]; then printf '%s\n' "$override"; return 0; fi
  "${OU_PYTHON:-python3}" "$(dirname "${BASH_SOURCE[0]}")/gate_test_cache.py" slots
}

# _ou_slot_take PREFIX COUNT MESSAGE: holds one of COUNT lock files <slot dir>/<PREFIX><N> on a descriptor of the calling
# shell and sets _ou_slot_fd and _ou_slot_index. Each slot is tried once without blocking; when all are busy, MESSAGE
# goes to stderr and one blocking flock(2) per slot waits on that slot's open descriptor (_ou_slot_wait), so the kernel
# wakes the waiter on whichever slot frees first (the lock belongs to the open file description the shell shares with
# the child). The first to take its slot wins; every other descriptor is closed, which drops a lock a second waiter
# took in the race. No interval: the wait ends on the release itself.
_ou_slot_take() {
  local prefix="$1" slots="$2" message="$3" dir i lock fd
  dir="${GATE_SLOT_DIR:-$(ou_config_value gate.slot_dir)}" || return
  local -a fds=()
  _ou_slot_fd="" _ou_slot_index=""
  for ((i = 1; i <= slots; i++)); do
    lock="$dir/$prefix$i"
    [[ -e "$lock" ]] || : >>"$lock" || { _ou_slot_close "${fds[@]}"; return 1; }
    if [[ ${EUID} -eq 0 || -O "$lock" ]]; then chmod 666 "$lock" 2>/dev/null || true; fi
    exec {fd}<"$lock" || { _ou_slot_close "${fds[@]}"; return 1; }
    if flock -n "$fd"; then
      _ou_slot_close "${fds[@]}"
      _ou_slot_fd="$fd" _ou_slot_index="$i"
      return 0
    fi
    fds+=("$fd")
  done
  echo "$message" >&2
  _ou_slot_index="$("${OU_PYTHON:-python3}" -c "$_ou_slot_wait" "${fds[@]}")" || _ou_slot_index=""
  [[ "$_ou_slot_index" =~ ^[1-9][0-9]*$ && $_ou_slot_index -le $slots ]] || { _ou_slot_close "${fds[@]}"; return 1; }
  _ou_slot_fd="${fds[_ou_slot_index - 1]}"
  for ((i = 0; i < slots; i++)); do
    [[ $((i + 1)) -eq $_ou_slot_index ]] || _ou_slot_close "${fds[i]}"
  done
  return 0
}

# The blocking wait of _ou_slot_take: one thread per inherited slot descriptor blocks in flock(2); the first to get its
# slot prints its number (1-based) and the process exits, which ends the other waits.
_ou_slot_wait='
import fcntl, os, sys, threading
won = threading.Lock()
def take(number, fd):
    fcntl.flock(fd, fcntl.LOCK_EX)
    if won.acquire(blocking=False):
        os.write(1, b"%d" % number)
        os._exit(0)
for number, fd in enumerate(sys.argv[1:], 1):
    threading.Thread(target=take, args=(number, int(fd)), daemon=True).start()
threading.Event().wait()
'

_ou_slot_close() {
  local fd
  for fd in "$@"; do exec {fd}<&-; done
}

ou_gate_slot_acquire() {
  local slots dir
  slots="$(ou_gate_slot_count)"
  dir="${GATE_SLOT_DIR:-$(ou_config_value gate.slot_dir)}"
  [[ "$slots" =~ ^[1-9][0-9]*$ ]] || { echo "GATE_SLOTS must be a positive integer" >&2; return 2; }
  OU_GATE_SLOTS="$slots"
  export OU_GATE_SLOTS
  # A gate started by a gate (a script test, a nested runner) shares the slot its parent already holds.
  [[ -z "${OU_GATE_SLOT:-}" ]] || return 0
  GATE_SLOT_DIR="$dir" _ou_slot_take tower-gate.slot "$slots" \
    "gate-local: all $slots gate slots in $dir are busy; waiting for one" || return
  OU_GATE_SLOT="$_ou_slot_index"
  OU_GATE_SLOT_OWNER="$$"
  export OU_GATE_SLOT OU_GATE_SLOT_OWNER
}

# GS1: a cap on the heavy database stages across every parallel gate run on this machine. Runs "$@" while holding one of
# gate.heavy_db_slots lock files in gate.slot_dir (the same directory as the gate slots), blocking until one frees
# (_ou_slot_take). The lock is held on a descriptor the command does not inherit, and is released when the command ends.
ou_gate_heavy_db_run() {
  local slots="${GATE_HEAVY_DB_SLOTS:-$(ou_config_value gate.heavy_db_slots)}" dir="${GATE_SLOT_DIR:-$(ou_config_value gate.slot_dir)}"
  local fd rc
  [[ "$slots" =~ ^[1-9][0-9]*$ ]] || { echo "GATE_HEAVY_DB_SLOTS must be a positive integer" >&2; return 2; }
  GATE_SLOT_DIR="$dir" _ou_slot_take tower-heavy-db.slot "$slots" \
    "gate: all $slots heavy database slots in $dir are busy; waiting for one" || return
  fd="$_ou_slot_fd"
  "$@" {fd}<&- && rc=0 || rc=$?
  exec {fd}<&-
  return "$rc"
}

# D-064 (f): the detached checkout of a --pr/--sha run lives at a path fixed per slot, not per worktree.
# Lint and tsc caches record absolute paths, so a per-worktree path made every new worktree lint cold.
# A slot is held by one gate at a time, so its path is never shared by two running gates. Only the
# gate that acquired the slot gets it; a nested gate (OU_GATE_SLOT inherited) gets nothing (status 1).
ou_gate_checkout_dir() {
  [[ -n "${OU_GATE_SLOT:-}" && "${OU_GATE_SLOT_OWNER:-}" == "$$" ]] || return 1
  # D-165: uid 0 without env.sh (the e2-micro runner) must not slot under a private home: initdb as ou-postgres and the
  # uid 65534 assertions of root-identity.test.sh could not reach the checkout ("Permission denied").
  local base="${GATE_CHECKOUT_ROOT:-}"
  if [[ -z "$base" && "${EUID:-$(id -u)}" -eq 0 ]]; then
    base="$(ou_config_value cloud.root_gate_checkout_root)" && mkdir -p "$base" && chmod a+rx "$base" 2>/dev/null || base=""
  fi
  printf '%s/slot%s\n' "${base:-$HOME/.cache/open-university/gate-checkouts}" "$OU_GATE_SLOT"
}
