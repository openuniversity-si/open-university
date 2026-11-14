#!/usr/bin/env bash
# The generator's tests of the LIVE tree (D-173): no drift, every split owner regenerates, `generate --check`.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_gentree_*.py; do
  PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$test"
done
"$root/scripts/generate" --check --root "$root" >/dev/null
