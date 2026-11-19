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
# D-322: the stage runs structure-check's PR part and commit-check's PR part, red when either is; the measurement
# checks' PR-body part left with the effort check (D-328).
tools="$(mktemp -d)"; trap 'rm -rf "$tools"' EXIT
mkdir -p "$tools/scripts"
# shellcheck disable=SC2016 # the fake's own shell expands it
printf '#!/usr/bin/env bash\necho "structure $*"; exit "${STRUCTURE_CODE:-0}"\n' > "$tools/scripts/structure-check"
# shellcheck disable=SC2016 # the fake's own shell expands it
printf '#!/usr/bin/env bash\necho "commits $*"; exit "${COMMIT_CODE:-0}"\n' > "$tools/scripts/commit-check"
chmod +x "$tools/scripts/structure-check" "$tools/scripts/commit-check"
# shellcheck disable=SC2016 # the child shell expands its own variables
prereq_run() { STRUCTURE_CODE="$1" COMMIT_CODE="${2:-0}" bash -c 'source "$1"
  root=R tool_root="$2" base=B pr="${3-N}" logs=L; gate_pr_metadata --no-publish' _ "$root/scripts/lib/gate-hooks/prereq.sh" "$tools" "${3-N}"; }
check "hook prereq runs the two parts of pr metadata" test "$(prereq_run 0)" = "structure --metadata --base B --pr N --snapshot L/pr-snapshot.json --no-publish
commits --pr N --root R"
check "hook prereq runs no commit part without a PR" test "$(prereq_run 0 0 "")" = "structure --metadata --base B --snapshot L/pr-snapshot.json --no-publish"
prereq_red() { ! prereq_run 1 >/dev/null; }
check "hook prereq is red when the structure part is" prereq_red
commits_red() { ! prereq_run 0 1 >/dev/null; }
check "hook prereq is red when the commit part is" commits_red
check_done
