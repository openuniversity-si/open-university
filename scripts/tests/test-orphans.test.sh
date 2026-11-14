#!/usr/bin/env bash
# The orphan-test check (TX25, D-070): every test_*.py is run by exactly one wrapper. Hermetic: temp dirs.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_test_orphans*.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$test"
done
