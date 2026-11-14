#!/usr/bin/env bash
# The cycle's turn guard (I-0d1c3a25): a temporary marker and transcript, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_cycle_stop.py"
