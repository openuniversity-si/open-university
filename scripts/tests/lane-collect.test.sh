#!/usr/bin/env bash
# A lane's collect: the diary note and closed row of a merged PR, once, and its ledger line (VAZÃO F69). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_lane_collect.py"
