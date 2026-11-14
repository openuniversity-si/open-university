#!/usr/bin/env bash
# The lane brief of one queue unit: its row, the delivery contract and a worktree (VAZÃO F68) Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_lane.py"
