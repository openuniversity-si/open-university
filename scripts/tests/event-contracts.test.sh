#!/usr/bin/env bash
# Event contracts (D-065, D-069 item 2): schemas, lock, natural keys, names. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_event_contracts.py"
