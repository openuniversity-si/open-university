#!/usr/bin/env bash
# gate-local hook `plan` (GX-38, D-070): called before the plan source is read (the PR classification or the batch plan).
# Owner: GX-20 (plan and carry, P-42). On a bound dev PR run, gate_carry.py decide reads the PR's passed v4 proofs and
# writes the carry decision; OU_GATE_CARRY_FILE hands it to gate_policy.py classify, which then plans delta(H0, head)
# and records the carried stages (carry.json in the logs). Anything it cannot decide is a normal gate (fails closed).
# Rollback: gate-carry.carry_over_enabled=false. A cold verdict (gate-verdict --cold, OU_GATE_COLD=1, D-075) never
# carries.
# shellcheck disable=SC2154 # py, tool_root, root, pr, dev, logs: the driver's, sourced first
gate_hook_plan() {
  unset OU_GATE_CARRY_FILE
  [[ "${dev:-0}" -eq 1 && -n "${pr:-}" && -n "${OU_GATE_PROOF:-}" && "${OU_GATE_COLD:-0}" != 1 ]] || return 0
  if "$py" "$tool_root/scripts/lib/gate_carry.py" decide --pr "$pr" --root "$root" --out "$logs/carry-decision.json"; then
    export OU_GATE_CARRY_FILE="$logs/carry-decision.json"
  fi
  return 0
}
