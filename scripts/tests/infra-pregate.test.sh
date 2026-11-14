#!/usr/bin/env bash
# PRE-GATE: at each push of a unit branch the live service asks the runner for the gate's plan with the check jobs'
# bodies and makes them, memoized by content, so the delivery's gate is answered by the cache. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_pregate.py"
