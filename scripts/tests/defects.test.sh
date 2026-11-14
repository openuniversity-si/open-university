#!/usr/bin/env bash
# The known-defect registry (KD1, D-069 items 4, 8 and 9): fixture register in a temp dir, in-memory forge log, injected clock. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_defects.py'
