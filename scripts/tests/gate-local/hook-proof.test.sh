#!/usr/bin/env bash
# Hook proof (GX-10): owned by the v4 binding.
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
# GX-10 owns `proof` (the v4 binding, scripts/tests/test_gate_report_v4.py); a run with no recorded base stays unbound.
# shellcheck disable=SC2016 # the child shell expands its own $1
check "hook proof binds nothing without a base" bash -c 'source "$1"; sha=x base="" OU_GATE_PASS_EXTRA=""; gate_hook_proof; [[ -z "$OU_GATE_PASS_EXTRA" && -z "${OU_GATE_PROOF:-}" ]]' _ "$root/scripts/lib/gate-hooks/proof.sh"
check_done
