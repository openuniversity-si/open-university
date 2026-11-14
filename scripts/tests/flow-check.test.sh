#!/usr/bin/env bash
# One report for the flow check: the clock in BRT, the lanes' pace, the train, the base's real gate, the program's units and the next decision number (D-197). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_flow_check.py"
