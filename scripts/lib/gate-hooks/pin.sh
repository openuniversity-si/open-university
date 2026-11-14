#!/usr/bin/env bash
# gate-local hook `pin` (GX-38, D-070): called before the preflight and before the lock, slot and worktree.
# Owner: GX-05 (pinned gate; B-09, GA-PG1). A --pr/--sha run is judged by the base tip's tooling: gate_pin.py resolves the
# base sha, prints `gate: pinned to <base sha>` first, runs that tooling's gate-local with OU_GATE_PINNED and this checkout
# as the record root, then (on a gate change) this head's tooling --report-only as advisory, and the driver exits with
# the pinned verdict. gate-pin.enabled=false (read by gate_pin.py) is the rollback: this checkout's tooling runs with
# OU_GATE_PINNED=off. A pin that cannot resolve ends the run with the classified abort `gate pin`.
# shellcheck disable=SC2154 # report_only, pr, sha, gate_args, py, tool_root, driver_abort: the driver's, sourced first
gate_hook_pin() {
  local pin_abort pin_rc=0 pin_message
  [[ -z "$pin_state" && $report_only -eq 0 && ( -n "$pr" || -n "$sha" ) ]] || return 0
  pin_abort="$(mktemp)"
  env OU_CONFIG_STORE=file "$py" "$tool_root/scripts/lib/gate_pin.py" run --root "$tool_root" --abort-file "$pin_abort" -- "${gate_args[@]}" || pin_rc=$?
  pin_message="$(cat "$pin_abort")"
  rm -f "$pin_abort"
  [[ -z "$pin_message" ]] || driver_abort "gate pin" "$pin_message"
  exit "$pin_rc"
}

# The hand-off of gate_pin.py, read once the tool root is known (before any path hangs off the record root). It is
# trusted only by the tooling it pinned (its HEAD is OU_GATE_PINNED), by a report-only run, or as the rollback's
# OU_GATE_PINNED=off; it is consumed here, so a gate a test starts inside this one never inherits the caller's record
# root, PR identity or pin. Sets pin_state, pin_identity and src_root for the driver.
# shellcheck disable=SC2034 # the driver reads the three
gate_pin_handoff() {
  pin_state="" pin_identity="" src_root="$tool_root"
  if [[ "${OU_GATE_PINNED:-}" == off || ( -n "${OU_GATE_PINNED:-}" && "$OU_GATE_PINNED" == "$(git -C "$tool_root" rev-parse HEAD)" ) ]]; then
    pin_state="$OU_GATE_PINNED"
  fi
  if [[ $report_only -eq 1 || ( -n "$pin_state" && "$pin_state" != off ) ]]; then
    src_root="${OU_GATE_RECORD_ROOT:-$tool_root}"
    [[ $report_only -eq 1 ]] || pin_identity="${OU_GATE_PR_IDENTITY:-}"
  fi
  unset OU_GATE_PINNED OU_GATE_RECORD_ROOT OU_GATE_PR_IDENTITY OU_GATE_VERSION
}
