#!/usr/bin/env bash
# Hook prereq (GX-15): owned by the structure check split (tree part, `pr metadata` stage).
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
# GX-15: the prereq hook names its tool root for the tree-only `structure check`, clears it, and launches `pr metadata`
# with the run's base and PR; a run that publishes no events (report-only) passes --no-publish.
# shellcheck disable=SC2016 # the child shell expands its own variables
prereq_launch() { bash -c 'source "$1"; [[ "$OU_STRUCTURE_TREE_ONLY" == "$2" ]] || exit 1; launch() { printf "%s|" "$@"; }
  root=R tool_root=T base=B pr=N logs=L event_pr="$3"; gate_hook_prereq; [[ -z "${OU_STRUCTURE_TREE_ONLY:-}" ]]' _ "$root/scripts/lib/gate-hooks/prereq.sh" "$root" "$1"; }
check "hook prereq launches pr metadata and clears the tree-only mark" test "$(prereq_launch N)" = "step|pr metadata|R|T/scripts/structure-check|--metadata|--base|B|--pr|N|--snapshot|L/pr-snapshot.json|"
check "hook prereq publishes nothing for a report-only run" test "$(prereq_launch "")" = "step|pr metadata|R|T/scripts/structure-check|--metadata|--base|B|--pr|N|--snapshot|L/pr-snapshot.json|--no-publish|"
check_done
