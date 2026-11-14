#!/usr/bin/env bash
# The one generator (D-069 items 1 and 2): target registry, renderers and the drift check, on FIXTURES. No network.
# The tests that read the live tree are `generate-tree.test.sh` (D-173): this half hits when only the tree changed.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_generate*.py "$root"/scripts/tests/test_aggregates*.py; do
  PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$test"
done
