#!/usr/bin/env bash
# The unit manifests (D-067): the contract, the lookups, the map generator and the ownership check. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_unit*.py; do
  [ -e "$test" ] || continue
  PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$test"
done
