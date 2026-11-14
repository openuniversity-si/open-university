#!/usr/bin/env bash
# Programs as first-class objects (D-069 CO1): the registry, the plan graph and the status folded from events, and the
# live plan folded from its plan.changed log (D-071 LP3) and the triage of plan inputs (LP4). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
# test_program.py stays exact: test_program_gate.py is coordinator.test.sh's.
for test in "$root"/scripts/tests/test_program.py "$root"/scripts/tests/test_plan_live*.py "$root"/scripts/tests/test_plan_triage*.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$test"
done
