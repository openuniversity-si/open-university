#!/usr/bin/env bash
# Shared by gate-local and its orchestration regression tests. The caller supplies logs and verbose.
# shellcheck source=scripts/lib/gate-budget.sh
source "$(dirname "${BASH_SOURCE[0]}")/gate-budget.sh"
logs="${logs:?}" verbose="${verbose:-0}"
gate_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# GV1: the live status comment. A run without a PR has no status.json, so every call is a no-op; a failure never
# reaches the gate result.
gate_status() {
  [[ "$1" == begin || -f "$logs/status.json" ]] || return 0
  "${OU_PYTHON:-python3}" "$gate_lib_dir/gate_status.py" "$@" --logs "$logs" >/dev/null 2>>"$logs/status.log" || true
}
# GX-19 (GA-PG5): the stage runs in the background under a watchdog that stops it, and everything it started, after
# gate-gc.stage_timeout_s[<stage>] seconds (gate_gc.py limits). A stage may be a shell function, so `timeout(1)` cannot be
# used. An overrun ends with gate-gc.timeout_exit_code; the limit is left in "$log.limit" for the failure report. The
# caller (step) owns name, log and dir: bash locals are visible here.
# TX10: one pass over a frozen tree. Signalled one at a time, a shell whose child died first ran its next command (a
# stage printed the line after its killed `sleep`; the watcher, B8, marked a stage that had already finished), and the
# stage ending mid-walk let the caller stop the watcher with the rest of the tree unsignalled. So every process is
# stopped first, parents before children (each listed while it is stopped, so it starts no other); then all are
# signalled; then continued leaves first, so each dies of its pending signal before its parent runs again.
gate_tree_stop() {
  local pid="$1" child
  kill -STOP "$pid" 2>/dev/null || return 0
  printf '%s\n' "$pid"
  for child in $(pgrep -P "$pid" 2>/dev/null); do gate_tree_stop "$child"; done
}
gate_kill_tree() {
  local sig="$1" tree i
  mapfile -t tree < <(gate_tree_stop "$2")
  for ((i = 0; i < ${#tree[@]}; i++)); do kill "-$sig" "${tree[i]}" 2>/dev/null || true; done
  for ((i = ${#tree[@]} - 1; i >= 0; i--)); do kill -CONT "${tree[i]}" 2>/dev/null || true; done
}
# shellcheck disable=SC2154 # name, log and dir are step's locals
# The stage's end reaches the watcher on a FIFO, never as a signal: a signal that lands on a subshell bash has just
# forked, before it resets the traps it inherited, runs the caller's EXIT trap in that subshell (gate-local's finish,
# a test's rm -rf of its work dir). A stage that ended at once hit that window about 1 time in 75 (BASEFIX-shellcheck).
gate_run_limited() {
  local limit grace tail_lines pid watcher rc ended
  gate_timeout_rc=""
  rm -f "$log.timedout"
  IFS=$'\t' read -r limit grace gate_timeout_rc tail_lines < <("${OU_PYTHON:-python3}" "$gate_lib_dir/gate_gc.py" limits "$name") || limit=0
  if [[ ! "$limit" =~ ^[0-9]+$ || "$limit" -eq 0 ]]; then
    (cd "$dir" && "$@") >"$log" 2>&1
    return
  fi
  printf '%s' "$limit" >"$log.limit"
  printf '%s' "$tail_lines" >"$log.tail"
  rm -f "$log.ended"
  mkfifo "$log.ended" || return 1
  exec {ended}<>"$log.ended"
  (cd "$dir" && "$@") {ended}>&- >"$log" 2>&1 &
  pid=$!
  (
    ! read -r -t "$limit" -u "$ended" _ || exit 0  # the stage ended within its limit
    kill -0 "$pid" 2>/dev/null || exit 0  # B8: the stage already ended; nothing timed out
    : >"$log.timedout"
    gate_kill_tree TERM "$pid"
    # The grace ends when the stage does: the main shell writes to the FIFO the moment `wait` returns, so a stage that
    # dies on TERM no longer costs the whole grace; only one still alive after it is killed.
    read -r -t "$grace" -u "$ended" _ || true
    ! kill -0 "$pid" 2>/dev/null || gate_kill_tree KILL "$pid"
  ) &
  watcher=$!
  wait "$pid"; rc=$?
  printf 'ended\n' >&"$ended"
  wait "$watcher" 2>/dev/null || true
  exec {ended}>&-
  rm -f "$log.ended"
  # The label is read once, after the watcher is gone: step reports a timeout only when this marker exists.
  if [[ -f "$log.timedout" ]]; then
    rc="$gate_timeout_rc"
    printf 'gate-gc: stage "%s" timed out after %ss\n' "$name" "$limit" >>"$log"
  fi
  return "$rc"
}
step() {
  local name="$1" dir="$2"; shift 2
  local log="$logs/${name//[^a-zA-Z0-9]/_}.log" record="$logs/${name//[^a-zA-Z0-9]/_}.stage.json" t0 rc elapsed
  gate_status stage-start --name "$name"
  t0=$(gate_now_ms)
  gate_run_limited "$@"; rc=$?
  elapsed=$(( $(gate_now_ms) - t0 ))
  # TX10: a record that cannot be written fails the stage here, naming its path, instead of a later reader's
  # FileNotFoundError.
  if ! python3 - "$record" "$name" "$rc" "$elapsed" <<'PYDATA'
import json, sys, time
from pathlib import Path
seconds = int(sys.argv[4]) / 1000
# GX-38: started_at is the wall-clock start in epoch seconds, derived from the monotonic elapsed time measured above.
Path(sys.argv[1]).write_text(json.dumps({'name': sys.argv[2], 'result': 'PASS' if sys.argv[3] == '0' else 'FAIL', 'exit': int(sys.argv[3]), 'seconds': seconds, 'started_at': time.time() - seconds}))
PYDATA
  then
    printf 'FAIL %s (stage record not written: %s; log: %s)\n' "$name" "$record" "$log" >&2
    return 1
  fi
  gate_status stage-end --name "$name"
  # One write per completed stage keeps output grouped when several stages finish together.
  {
    if [[ $verbose -eq 1 ]]; then cat "$log"; fi
    if [[ $rc -eq 0 ]]; then
      printf 'PASS %s (%d.%03ds)\n' "$name" "$((elapsed / 1000))" "$((elapsed % 1000))"
      if [[ $verbose -eq 0 ]]; then
        grep -E 'Test Files|Tests +[0-9]+ passed|tests:.*passed|[0-9]+ passed|[0-9]+ skipped|Total: [0-9]+ tests|build cache|host allow-list:|tower-media retries:' "$log" || true
      fi
    else
      # TX10: the full log stays in this run's own $logs (never a fixed host-wide path a sibling run overwrites).
      printf 'FAIL %s (%d.%03ds; exit %d; log: %s)\n' "$name" "$((elapsed / 1000))" "$((elapsed % 1000))" "$rc" "$log"
      if [[ -f "$log.timedout" ]]; then
        # GX-19: a stage that overran its limit is env whatever its partial log says (an assertion printed before the
        # hang is not the cause): the log tail, then the machine line.
        tail -n "$(cat "$log.tail")" "$log" | cut -c1-200
        "${OU_PYTHON:-python3}" "$gate_lib_dir/gate_classify.py" abort "$name" "FAIL env: stage \"$name\" ran past gate-gc.stage_timeout_s ($(cat "$log.limit")s) and was killed" || true
      else
        grep -E 'error|Error|FAIL|✗|×|failed|leak' "$log" | grep -v node_modules | head -8 | cut -c1-200 || true
        # D-027: code, env or contract, with the action AGENTS.md prescribes, then the machine line
        # `<gate.class_line_prefix> <stage>\t<class>` (GX-01) that the train reads.
        "${OU_PYTHON:-python3}" "$gate_lib_dir/gate_classify.py" "$name" "$log" || true
      fi
    fi
  } >"$log.result"
  if [[ "${EUID}" -eq 0 ]]; then
    : >>"$logs/output.lock"
    chmod 666 "$logs/output.lock"
  fi
  flock "$logs/output.lock" cat "$log.result"
  return "$rc"
}
# D-065 V6 (M5): tier-1 result cache. The key comes from gate_result_cache.py and is empty outside tier 1, so tiers 2
# and 3 always run the command. A hit skips the command and is recorded as cached; only a pass is stored.
# shellcheck disable=SC2154 # cache is the caller's (gate-local) directory
step_cached() {
  local name="$1" dir="$2" key="$3" py="${OU_PYTHON:-python3}"
  shift 3
  if [[ -z "$key" ]]; then
    step "$name" "$dir" "$@"
    return
  fi
  if "$py" "$gate_lib_dir/gate_result_cache.py" hit --cache "$cache" --key "$key"; then
    "$py" "$gate_lib_dir/gate_result_cache.py" record-cached --logs "$logs" --step "$name" --key "$key" || return 1
    printf 'PASS %s (cached: tier-1 result %s)\n' "$name" "$key"
    return 0
  fi
  step "$name" "$dir" "$@" || return 1
  "$py" "$gate_lib_dir/gate_result_cache.py" store --cache "$cache" --key "$key"
}
# GS1: the cache key of a stage declared deterministic in gate-stages.json ("" when it must run). SCOPE is the selection
# the stage runs under, so a pass over some files is never reused for a run over others.
# OU-DECOUPLE F5 (D-113): the key reads the checkout alone; the web package directory (--web) left with Open University.
gate_stage_key() {
  "${OU_PYTHON:-python3}" "$gate_lib_dir/gate_result_cache.py" stage-key --mode "${mode:-}" --root "${root:?}" \
    --stage "$1" --scope "${2:-}" 2>/dev/null || true
}
# Compute input keys inside the launched task: command substitution in a launch argument would serialize hashing
# ahead of independent metadata and classification, despite the dependency graph declaring no dependency.
step_cached_by_inputs() {
  local name="$1" dir="$2" scope="$3"
  shift 3
  step_cached "$name" "$dir" "$(gate_stage_key "$name" "$scope")" "$@"
}
# GK1 (D-069 item 12): `failed` only says the verdict is red. A later stage waits on a failure only when it cannot run
# without it: the caller names that dependency with gate_block, and every
# stage started through gate_unless_blocked is then recorded as skipped (gate_skips.py) instead of silently missing.
gate_blocked=""
gate_block() { [[ -n "$gate_blocked" ]] || gate_blocked="$1"; }
# gate_skip STAGE [BLOCKER]: BLOCKER defaults to the gate-wide dependency; a stage-local one is named.
gate_skip() {
  local blocker="${2:-$gate_blocked}"
  printf 'SKIP %s (skipped: %s failed)\n' "$1" "$blocker"
  "${OU_PYTHON:-python3}" "$gate_lib_dir/gate_skips.py" record --logs "$logs" --name "$1" --blocked-by "$blocker"
}
# gate_unless_blocked STAGE CMD...: runs CMD (a step call) unless a hard dependency failed; a skip is not a failure.
gate_unless_blocked() {
  local stage="$1"
  shift
  if [[ -n "$gate_blocked" ]]; then
    gate_skip "$stage"
    return 0
  fi
  "$@"
}
pids=()
launch() { "$@" & pids+=("$!"); }
# dev=0 (nightly, tier 3, legacy) runs every stage. A missing plan file also runs every stage.
# A scoped dev plan runs a stage only when gate-areas.json required it.
gate_want() {
  local name="$1"
  if [[ "${dev:-0}" -eq 0 || -z "${GATE_PLAN_FILE:-}" || ! -f "${GATE_PLAN_FILE}" ]]; then
    return 0
  fi
  "${OU_PYTHON:-python3}" - "$name" "$GATE_PLAN_FILE" <<'PY'
import json, sys
plan = json.load(open(sys.argv[2]))
sys.exit(0 if sys.argv[1] in plan.get("stages", []) else 1)
PY
}
join_steps() {
  local pid rc=0
  for pid in "${pids[@]}"; do wait "$pid" || rc=1; done
  pids=()
  return "$rc"
}

secret_tree() {
  # Scan every tracked or unignored source file, including dirty/untracked source. Ignored build output is not source.
  # GATE-SPEED (D-092): with a base and gate.leak_scan_scope `change` ($1 $2), only the files the PR changes or
  # leaves untracked; gate-noite and a .gitleaks.toml change scan the whole tree (gate_speed.py secret-files).
  local scan source_root="$PWD" listing scope=full
  scan=$(mktemp -d "$logs/source-scan.XXXXXX") || return 1
  listing="$scan.list"
  if [[ -n "${1:-}" ]]; then
    scope=$("$py" "$gate_lib_dir/gate_speed.py" secret-files "$PWD" "$1" "$2" "$listing") || return 1
  fi
  if [[ "$scope" != change ]]; then
    git ls-files --cached --others --exclude-standard --deduplicate -z >"$listing" || return 1
  fi
  echo "secret scan (tree): $scope scope, $(tr -cd '\0' <"$listing" | wc -c) file(s)"
  while IFS= read -r -d '' file; do [[ ! -f "$file" ]] || printf '%s\0' "$file"; done <"$listing" |
    tar --null -T - -cf - | tar -xf - -C "$scan" || return 1
  (cd "$scan" && gitleaks dir --config "$source_root/.gitleaks.toml" --redact --no-banner .)
}
