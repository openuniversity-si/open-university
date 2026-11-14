#!/usr/bin/env bash
# Counted integrated commits of the last 60 minutes, as a rate per second, minute, hour and day (D-201). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_commit_rate.py"
