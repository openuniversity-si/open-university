#!/usr/bin/env bash
# The next free decision number: after the base's last one and after every number an open PR cites (D-183). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_decision_next.py"
