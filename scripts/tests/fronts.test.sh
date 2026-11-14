#!/usr/bin/env bash
# The fronts in flight and a lane's collect (VAZÃO F69). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_fronts.py"
