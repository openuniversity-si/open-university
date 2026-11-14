#!/usr/bin/env bash
# D-064 (b): gate isolation per worktree. Sourced by scripts/cloud/env.sh and scripts/gate-local.
# - ou_test_db_name: the local test database is derived from the checkout path, so one gate's
#   schema reset, migrate and seed never touch another worktree's database.
# - ou_test_db_ensure: creates that database on demand in the shared local PostgreSQL.
# - ou_gate_slot_acquire: a global semaphore of GATE_SLOTS (default 3) concurrent gates.
# - ou_gate_checkout_dir: the fixed per-slot path of a --pr/--sha checkout (warm lint/tsc caches).
# shellcheck shell=bash

# tower_test_<10 hex of sha256(checkout path)>. Hex never starts with "g", so it cannot match the
# integration databases (tower_test_g<random>) that test/int-teardown.ts creates and drops.
ou_test_db_name() {
  local path="${1:?checkout path}" digest
  digest="$(printf '%s' "$path" | sha256sum)" || return
  printf 'tower_test_%s\n' "${digest:0:10}"
}

# Creates the database named in TEST_DATABASE_URL when it is missing. Local PostgreSQL only.
ou_test_db_ensure() {
  local url="${1:-${TEST_DATABASE_URL:-}}" name admin
  [[ "$url" =~ ^postgres(ql)?://[^/]*@(127\.0\.0\.1|localhost)(:[0-9]+)?/([A-Za-z0-9_]+)$ ]] || {
    echo "ou_test_db_ensure: TEST_DATABASE_URL is not a local PostgreSQL database" >&2
    return 2
  }
  name="${BASH_REMATCH[4]}"
  admin="${url%/*}/postgres"
  [[ "$(psql "$admin" -qtAc "select 1 from pg_database where datname = '$name'" 2>/dev/null)" == 1 ]] && return 0
  # A concurrent creator of the same name loses with "already exists"; the re-check below accepts it.
  psql "$admin" -qtAc "create database \"$name\"" >/dev/null 2>&1 || true
  [[ "$(psql "$admin" -qtAc "select 1 from pg_database where datname = '$name'" 2>/dev/null)" == 1 ]] || {
    echo "ou_test_db_ensure: could not create local test database $name" >&2
    return 1
  }
}

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

ou_gate_slot_acquire() {
  local slots dir
  slots="$(ou_gate_slot_count)"
  dir="${GATE_SLOT_DIR:-$(ou_config_value gate.slot_dir)}"
  local poll="${GATE_SLOT_POLL:-$(ou_config_value gate.slot_poll_s)}" i lock fd waited=0
  [[ "$slots" =~ ^[1-9][0-9]*$ ]] || { echo "GATE_SLOTS must be a positive integer" >&2; return 2; }
  OU_GATE_SLOTS="$slots"
  export OU_GATE_SLOTS
  # A gate started by a gate (a script test, a nested runner) shares the slot its parent already holds.
  [[ -z "${OU_GATE_SLOT:-}" ]] || return 0
  while :; do
    for ((i = 1; i <= slots; i++)); do
      lock="$dir/tower-gate.slot$i"
      [[ -e "$lock" ]] || : >>"$lock" || return
      if [[ ${EUID} -eq 0 || -O "$lock" ]]; then chmod 666 "$lock" 2>/dev/null || true; fi
      exec {fd}<"$lock" || return
      if flock -n "$fd"; then
        OU_GATE_SLOT="$i"
        OU_GATE_SLOT_OWNER="$$"
        export OU_GATE_SLOT OU_GATE_SLOT_OWNER
        return 0
      fi
      exec {fd}<&-
    done
    if [[ $waited -eq 0 ]]; then
      echo "gate-local: all $slots gate slots in $dir are busy; waiting for one" >&2
      waited=1
    fi
    sleep "$poll"
  done
}

# GS1: a cap on the heavy database stages across every parallel gate run on this machine. Runs "$@" while holding one of
# gate.heavy_db_slots lock files in gate.slot_dir (the same directory and poll as the gate slots), waiting for a free
# one. The lock is held on a descriptor the command does not inherit, and is released when the command ends.
ou_gate_heavy_db_run() {
  local slots="${GATE_HEAVY_DB_SLOTS:-$(ou_config_value gate.heavy_db_slots)}" dir="${GATE_SLOT_DIR:-$(ou_config_value gate.slot_dir)}"
  local poll="${GATE_SLOT_POLL:-$(ou_config_value gate.slot_poll_s)}" i lock fd waited=0 rc
  [[ "$slots" =~ ^[1-9][0-9]*$ ]] || { echo "GATE_HEAVY_DB_SLOTS must be a positive integer" >&2; return 2; }
  while :; do
    for ((i = 1; i <= slots; i++)); do
      lock="$dir/tower-heavy-db.slot$i"
      [[ -e "$lock" ]] || : >>"$lock" || return
      if [[ ${EUID} -eq 0 || -O "$lock" ]]; then chmod 666 "$lock" 2>/dev/null || true; fi
      exec {fd}<"$lock" || return
      if flock -n "$fd"; then
        "$@" {fd}<&- && rc=0 || rc=$?
        exec {fd}<&-
        return "$rc"
      fi
      exec {fd}<&-
    done
    if [[ $waited -eq 0 ]]; then
      echo "gate: all $slots heavy database slots in $dir are busy; waiting for one" >&2
      waited=1
    fi
    sleep "$poll"
  done
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
