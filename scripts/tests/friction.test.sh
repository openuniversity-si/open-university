#!/usr/bin/env bash
# one lane friction per line, clock ts and a closed cause (VAZÃO F85) Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_friction.py"
