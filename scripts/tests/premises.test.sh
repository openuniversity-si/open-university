#!/usr/bin/env bash
# The premise register and scripts/premises (D-066) on fixture registers. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_premises.py"
