#!/usr/bin/env bash
# The shadow run of the real gate (D-151). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_gate_shadow.py"
