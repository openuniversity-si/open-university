#!/usr/bin/env bash
# The local checks run the structure check before every push (lane 4, D-236). Reads one file; no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_structure_wiring.py"
