# shellcheck shell=bash
# The shared setup of a gate-local suite part (scripts/tests/gate-local/*.test.sh): the real runner with stub workloads,
# a private work dir and the check helper. A part sources this file and edits nothing shared (TX-PROGRAM, D-070).
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
logs="$work/logs"; mkdir -p "$logs"
verbose=0
# shellcheck source=scripts/lib/gate-runner.sh
source "$root/scripts/lib/gate-runner.sh"
CHECK_LABEL="gate runner"
# shellcheck source=scripts/tests/lib/check.sh
source "$root/scripts/tests/lib/check.sh"
