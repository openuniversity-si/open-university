#!/usr/bin/env bash
# The explicit, reversible gate bypass (D-151). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_gate_bypass.py"
