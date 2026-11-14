#!/usr/bin/env bash
# Writes one decision record, docs/domain/decisions/D-NNN.md, with its number and time from the claim (D1, D-217). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_decision_record.py"
