#!/usr/bin/env bash
# PS1: production entrypoints refused in cloud sessions and PR diffs (D-054, D-069 item 13). Hermetic, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$root/scripts/tests/test_production_guard.py"
