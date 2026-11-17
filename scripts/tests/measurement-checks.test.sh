#!/usr/bin/env bash
# The gate's measurement checks stage (D-322): census, absolute baseline, shared literals, budgets and the PR body's
# effort block, on fixture repositories. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$root/scripts/tests/test_measurement_checks.py"
