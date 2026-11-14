#!/usr/bin/env bash
# GX-01: the real driver runs the gate preflight before the lock, the slot and the worktree.
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
# GX-01 (D-070): the real driver runs the gate preflight before the lock, the slot and the worktree. An empty toolchain
# is a gap: the run ends with exit 2 in seconds, prints `FAIL env: <gap>` and one class line, and leaves nothing behind.
pre="$work/preflight"; mkdir -p "$pre/toolchain" "$pre/slots"
started=$(date +%s)
rc=0; env OU_TOOLCHAIN_DIR="$pre/toolchain" GATE_LOCK_FILE="$pre/gate.lock" GATE_SLOT_DIR="$pre/slots" \
  GATE_RECORD_DIR="$pre/records" "$root/scripts/gate-local" --dev >"$pre/out" 2>&1 || rc=$?
elapsed=$(( $(date +%s) - started ))
prefix="$(python3 "$root/scripts/lib/config.py" get gate.class_line_prefix | tr -d '"')"
budget="$(python3 "$root/scripts/lib/config.py" get env.gate_preflight_budget_s)"
setup_exit="$(cd "$root/scripts/lib" && python3 -c 'import preflight; print(preflight.SETUP_EXIT)')"
check "a preflight gap exits with the setup code" test "$rc" = "$setup_exit"
check "a preflight gap ends the run within env.gate_preflight_budget_s" test "$elapsed" -lt "$budget"
check "each gap is a FAIL env line" grep -q '^FAIL env: missing toolchain: ' "$pre/out"
check "the abort prints one class line" test "$(grep -c "^$prefix gate preflight"$'\t'"env\$" "$pre/out")" = 1
check "no lock file was taken before the preflight" test ! -e "$pre/gate.lock"
check "no slot was taken before the preflight" test -z "$(ls -A "$pre/slots")"
check "no record dir or gate checkout was made" test ! -e "$pre/records"
check "the preflight runs before the lock" test "$(grep -n 'driver_abort "gate preflight"' "$root/scripts/gate-local" | cut -d: -f1)" -lt "$(grep -n "^exec 9>\"\$lock\"" "$root/scripts/gate-local" | cut -d: -f1)"
# The registered switch gate.preflight_enabled is the one-key rollback of a false positive.
check "gate.preflight_enabled is read by the driver" grep -Fq 'get gate.preflight_enabled' "$root/scripts/gate-local"
check_done
