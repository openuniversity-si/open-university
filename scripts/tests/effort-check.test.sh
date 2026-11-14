#!/usr/bin/env bash
# The cheapest-useful-effort check through the structure check, on fixture repositories (EFFORT-STEP). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
exec python3 "$root/scripts/tests/test_structure_effort.py"
