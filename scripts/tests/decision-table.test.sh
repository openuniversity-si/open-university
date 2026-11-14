#!/usr/bin/env bash
# Renders the rows of DECISIONS.md from the decision records, one row per record, in number order (D1, D-217). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_decision_table.py"
