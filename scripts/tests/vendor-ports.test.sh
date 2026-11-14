#!/usr/bin/env bash
# The engine's vendor ports and adapters (D-069 item 7, R1): fake adapters, fake runners, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_ports_*.py "$root"/scripts/tests/test_vendor_check.py "$root"/scripts/tests/test_vendor_classification.py; do
  [ -e "$test" ] || continue
  PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$test"
done
