#!/usr/bin/env bash
# Hook plan (GX-20): owned by carry-over by delta.
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
# GX-20 owns `plan` (carry-over by delta, scripts/tests/test_gate_carry.py); a run with no proof binding decides nothing.
# shellcheck disable=SC2016 # the child shell expands its own $1
check "hook plan decides no carry without a proof binding" bash -c 'source "$1"; dev=1 pr=1; unset OU_GATE_PROOF; OU_GATE_CARRY_FILE=x; gate_hook_plan; [[ -z "${OU_GATE_CARRY_FILE:-}" ]]' _ "$root/scripts/lib/gate-hooks/plan.sh"
check_done
