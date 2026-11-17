#!/usr/bin/env bash
# The checks the merge queue requires (CHK, D-320): every workflow job is a check, staged, installed or required, derived from services/runner/github/, .github/workflows/ and .github/rulesets/; a required check no installed job runs and an installed workflow that differs from its staged copy are refused. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_queue_checks.py"
