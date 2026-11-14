#!/usr/bin/env bash
# The whole life of a base defect (KD1): detected, registered, routed, resolved, verified. Fake runner, in-memory log. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_defect_lifecycle.py"
