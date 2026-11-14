#!/usr/bin/env bash
# Hook tier (GX-11): owned by the derived tier.
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
# GX-11 owns `tier` (the derived tier, scripts/tests/gate-tier.test.sh); it exports OU_GATE_TIER.
# shellcheck disable=SC2016 # the child shell expands its own $1
check "hook tier exports the derived tier" bash -c 'source "$1"; pr=N sha="" tier3=0; gate_hook_tier; test -n "$OU_GATE_TIER"' _ "$root/scripts/lib/gate-hooks/tier.sh"
check_done
