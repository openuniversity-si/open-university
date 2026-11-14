#!/usr/bin/env bash
# gate-local hook `prereq` (GX-38, D-070): called after the prerequisite stages are launched and before they are joined; it may launch more (launch step ...).
# Owner: GX-15 (B-11, P-42). The structure check runs as two stages: `structure check` runs only the tree part (reused by
# content key, structure.tree_cache_enabled) and `pr metadata` the PR-metadata part, never cached, on every run (every
# plan expects it; without --pr it judges nothing). It publishes pr.checked v1 unless the run publishes no events (a
# report-only run has no event_pr). Sourcing this file names its tool root in OU_STRUCTURE_TREE_ONLY before `structure
# check` is launched; structure.py honours it only in that tool root, and the hook clears it once that stage has started,
# so no later stage (a script test's own structure-check) inherits it.
OU_STRUCTURE_TREE_ONLY="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
export OU_STRUCTURE_TREE_ONLY
# shellcheck disable=SC2154 # root, tool_root, base, pr, event_pr: the driver's, set before the hook is called
gate_hook_prereq() {
  local publish=()
  unset OU_STRUCTURE_TREE_ONLY
  [[ -n "${event_pr:-}" ]] || publish=(--no-publish)
  launch step "pr metadata" "$root" "$tool_root/scripts/structure-check" --metadata ${base:+--base "$base"} ${pr:+--pr "$pr"} --snapshot "$logs/pr-snapshot.json" "${publish[@]}"
}
