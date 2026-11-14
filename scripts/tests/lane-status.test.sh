#!/usr/bin/env bash
# One line per fact of the lane: counted commits per hour, the train queue, the train process, the newest shadow gate. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_lane_status.py"
