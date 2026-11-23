#!/usr/bin/env bash
# Autonomy ladder contract, active configuration, and eight external trust indicators (D-353, C8). Hermetic.
# Verifies: D-353, UNIT:engine-model
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_trust_metrics.py"
