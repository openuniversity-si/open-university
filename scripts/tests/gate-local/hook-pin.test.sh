#!/usr/bin/env bash
# Hook pin (GX-05): owned by the pinned gate.
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
# GX-05 owns `pin` (the pinned gate, scripts/tests/gate-pin.test.sh); it defines gate_hook_pin and the hand-off reader.
# shellcheck disable=SC2016 # $1 is the child shell's argument: pin.sh is sourced there, not into this test
check "hook pin defines gate_hook_pin and gate_pin_handoff" bash -c 'source "$1"; declare -F gate_hook_pin gate_pin_handoff >/dev/null' _ "$root/scripts/lib/gate-hooks/pin.sh"
check_done
