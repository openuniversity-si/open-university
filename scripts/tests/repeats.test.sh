#!/usr/bin/env bash
# The repeated actions of the program, from docs/process/repeats.md: the open ones first, by count (D-208). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_repeats.py"
