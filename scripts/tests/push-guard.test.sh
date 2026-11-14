#!/usr/bin/env bash
# The push guard (X1, D-022): hooks, replay-branch and stall report on fixture repositories and a fake forge. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_push_guard.py" --parallel
