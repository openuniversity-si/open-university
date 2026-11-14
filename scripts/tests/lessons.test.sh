#!/usr/bin/env bash
# The lessons registry (LR1, D-069 items 4 and 9): fixture register in a temp dir, injected clock. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_lesson*.py'
