#!/usr/bin/env bash
# GX-38: the driver hooks, each called once by gate-local at its fixed point, in order.
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
# GX-38 (D-070): six no-op driver hooks, each called once by gate-local at its fixed point, in this order. The call sites
# are read from the driver, the first one is also run for real (tier runs before the preflight), and a hook body
# changes nothing the driver prints.
hook_calls() { grep -n '^ *gate_hook [a-z]*$' "$root/scripts/gate-local" | sed -E 's/^([0-9]+): *gate_hook ([a-z]+)$/\2/'; }
check "each hook is called once, in order: tier, pin, proof, exit, prereq, plan" test "$(hook_calls | tr '\n' ' ')" = "tier pin proof exit prereq plan "
call_line() { grep -n "^ *gate_hook $1\$" "$root/scripts/gate-local" | head -1 | cut -d: -f1; }
in_driver_order() { local prev=0 n; for n in "$@"; do local l; l=$(call_line "$n"); [[ -n "$l" && "$l" -gt "$prev" ]] || return 1; prev=$l; done; }
check "the calls appear in the driver as tier, pin, proof, prereq, plan" in_driver_order tier pin proof prereq plan
check "the exit hook is the first line of the exit trap" test "$(grep -A2 '^finish() {' "$root/scripts/gate-local" | grep -c 'gate_hook exit')" = 1
check "pin selects tooling before its single preflight and the lock" test "$(call_line pin)" -lt "$(grep -n 'driver_abort "gate preflight"' "$root/scripts/gate-local" | cut -d: -f1)" -a "$(call_line pin)" -lt "$(grep -n "^exec 9>\"\$lock\"" "$root/scripts/gate-local" | cut -d: -f1)"
check "the proof hook follows the base and the base sha is exported" test "$(grep -c "^export OU_GATE_BASE_SHA=\"\$base\"\$" "$root/scripts/gate-local")" = 1
hk="$work/hooks"; mkdir -p "$hk/toolchain" "$hk/slots"
rc=0; env OU_GATE_HOOK_TRACE="$hk/trace" OU_TOOLCHAIN_DIR="$hk/toolchain" GATE_LOCK_FILE="$hk/gate.lock" GATE_SLOT_DIR="$hk/slots" \
  GATE_RECORD_DIR="$hk/records" "$root/scripts/gate-local" --dev >"$hk/out" 2>&1 || rc=$?
check "a real run reaches the tier hook once, before the preflight aborts it" test "$(tr '\n' ' ' <"$hk/trace")" = "tier pin "
check_done
