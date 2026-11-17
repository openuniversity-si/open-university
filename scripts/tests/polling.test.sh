#!/usr/bin/env bash
# The polling scan's decisions (PADRAO-DEV F8b): every sleep inside a loop is decided by file and function (backoff, dormant, test infrastructure, measurement, or a real wait on a state), no candidate is undecided and no decision is stale. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_polling.py"
