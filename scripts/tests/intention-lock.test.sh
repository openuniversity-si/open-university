#!/usr/bin/env bash
# Mechanical enforcement of the SEMENTE §6 intention lock (C4) and INT alignment checks. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_intention_lock.py"
