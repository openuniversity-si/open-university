#!/usr/bin/env bash
# GS1: the batch entry point (scripts/gate-batch, scripts/gate-dev --batch): usage errors never start a gate. Hermetic.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
python3 "$here/test_gate_batch.py"
fail() { echo "FAIL $*" >&2; exit 1; }
status() { local rc=0; "$@" >/dev/null 2>&1 || rc=$?; echo "$rc"; }
[[ "$(status "$here/../gate-batch")" == 2 ]] || fail "gate-batch without refs is a usage error"
[[ "$(status "$here/../gate-dev" --batch)" == 2 ]] || fail "gate-dev --batch without refs is a usage error"
[[ "$(status "$here/../gate-batch" no-such-ref-for-gs1)" == 2 ]] || fail "an unknown ref stops before the gate"
[[ "$(status "$here/../gate-batch" --base)" == 2 ]] || fail "--base needs a value"
grep -q -- '--plan-file' "$here/../gate-local" || fail "gate-local takes the batch plan"
echo "gate-batch: ok"
