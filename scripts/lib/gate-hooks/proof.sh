#!/usr/bin/env bash
# gate-local hook `proof` (GX-38, D-070): called once the base sha is known; OU_GATE_BASE_SHA is exported, and OU_GATE_PASS_EXTRA (key=value lines) is appended to the .pass record.
# Owner: GX-10 (proof, GA-P01). gate_proof.py bind fixes what the verdict is bound to (head and base trees, gate_version,
# toolchain_id, the selection request, input_digest, lane_id, the gate start and the driver's CPU ticks) and this hook
# exports it as OU_GATE_PROOF for gate_report's v4 verdict, OU_GATE_VERSION, and the .pass extras head_tree, base_sha,
# gate_version, toolchain_id and input_digest. A run it cannot bind (no sha or no recorded base) keeps the v3 verdict
# and a plain record. gate-proof.event_version=3 is the rollback of the event (read by gate_proof.py).
# shellcheck disable=SC2154 # py, tool_root, src_root, sha, base, mode, plan_file, gate_started_epoch (gate_started): the driver's, sourced first
gate_hook_proof() {
  local bound keys_file
  unset OU_GATE_PROOF OU_GATE_VERSION
  gate_run_key_parts=""
  [[ -n "$sha" && -n "$base" ]] || return 0
  keys_file=$(mktemp) || return 0
  if ! bound=$("$py" "$tool_root/scripts/lib/gate_proof.py" bind --src-root "$src_root" --tool-root "$tool_root" \
    --sha "$sha" --base "$base" --plan "$mode" --batch-file "$plan_file" --started-ms "${gate_started_epoch:-$gate_started}" --pid "$$" \
    --key-parts-file "$keys_file"); then
    rm -f "$keys_file"
    return 0
  fi
  # shellcheck disable=SC2034 # consumed by gate-local after this hook returns
  gate_run_key_parts=$(cat "$keys_file")
  rm -f "$keys_file"
  OU_GATE_PROOF="${bound%%$'\n'*}"
  OU_GATE_PASS_EXTRA="${bound#*$'\n'}"
  OU_GATE_VERSION="$(sed -n 's/^gate_version=//p' <<<"$OU_GATE_PASS_EXTRA")"
  export OU_GATE_PROOF OU_GATE_VERSION
}
