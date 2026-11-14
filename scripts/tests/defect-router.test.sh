#!/usr/bin/env bash
# The known-defect router (KD1, D-069 items 4, 8 and 9): priority from queue impact, fix unit routing. Fixture register, in-memory forge log. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_defect_router.py'
