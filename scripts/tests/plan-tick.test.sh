#!/usr/bin/env bash
# The plan tick (D-065 V4), pr.ready and the plan-tick registry on fixtures. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_plan_tick*.py "$root"/scripts/tests/test_gate_v4_readers*.py "$root"/scripts/tests/test_pr_ready*.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$test"
done
