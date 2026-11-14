#!/usr/bin/env bash
# one line per N7 check, pass/warn/fail, exit code; no session needed Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_checks.py"
