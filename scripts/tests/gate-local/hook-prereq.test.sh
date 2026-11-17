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
check "hook prereq launches pr metadata and clears the tree-only mark" test "$(prereq_launch N)" = "step|pr metadata|R|gate_pr_metadata|"
check "hook prereq publishes nothing for a report-only run" test "$(prereq_launch "")" = "step|pr metadata|R|gate_pr_metadata|--no-publish|"
# D-322: the stage runs structure-check's PR part and then the measurement checks' PR-body part; red when either is.
tools="$(mktemp -d)"; trap 'rm -rf "$tools"' EXIT
mkdir -p "$tools/scripts"
# shellcheck disable=SC2016 # the fake's own shell expands it
printf '#!/usr/bin/env bash\necho "structure $*"; exit "${STRUCTURE_CODE:-0}"\n' > "$tools/scripts/structure-check"
chmod +x "$tools/scripts/structure-check"
# shellcheck disable=SC2016 # the child shell expands its own variables
prereq_run() { STRUCTURE_CODE="$1" bash -c 'source "$1"; measured() { echo "measured $*"; return "${MEASURED_CODE:-0}"; }
  root=R tool_root="$2" base=B pr=N logs=L py=measured; gate_pr_metadata --no-publish' _ "$root/scripts/lib/gate-hooks/prereq.sh" "$tools"; }
check "hook prereq runs both parts of pr metadata" test "$(prereq_run 0)" = "structure --metadata --base B --pr N --snapshot L/pr-snapshot.json --no-publish
measured $tools/scripts/lib/measurement_checks.py body --base B --pr N"
prereq_red() { ! prereq_run 1 >/dev/null; }
check "hook prereq is red when the structure part is" prereq_red
check_done
