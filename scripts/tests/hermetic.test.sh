#!/usr/bin/env bash
# Hermetic tests (D-069 item 5, H1): the Python harness and the hermetic check. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_hermetic*.py; do
  PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$test"
done
