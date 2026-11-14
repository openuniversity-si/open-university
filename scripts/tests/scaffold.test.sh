#!/usr/bin/env bash
# The scaffold of a new script (FLUXO-AMPLO F1.2, D-146). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_scaffold.py"
