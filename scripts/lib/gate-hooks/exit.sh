#!/usr/bin/env bash
# gate-local hook `exit` (GX-38, D-070): called first in the exit trap, with the exit status in rc (read-only).
# GX-19: bounds the report directories and the build cache (gate-gc.reports_keep, gate-gc.build_cache_keep). The newest
# report directory is this run's own, so it always stays. GATE-GC-CHEIO: the sha directories of the folder are bounded
# too (gate-gc.reports_shas_keep, or gate-gc.report_only_shas_keep for the advisory run's own folder), never a live one
# (gate_gc.collect_shas). Hygiene never changes a verdict: a failure here is ignored.
# Owner after GX-38: GX-19 (exit).
gate_hook_exit() {
  [[ -n "${tool_root:-}" ]] || return 0
  local -a scope=()
  [[ "${report_only:-0}" -ne 1 ]] || scope+=(--report-only)
  # This run's own sha is live until the hook ends, and so is any sha a held lock names.
  [[ ! "${sha:-}" =~ ^[0-9a-f]{40}$ ]] || scope+=(--live-sha "$sha")
  [[ -z "${lock:-}" ]] || scope+=(--lock "$lock")
  "${py:-python3}" "$tool_root/scripts/lib/gate_gc.py" collect --reports "${record_dir:-}/reports" --build-cache "${cache:-}" "${scope[@]}" >/dev/null 2>&1 || true
}
