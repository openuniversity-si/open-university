#!/usr/bin/env bash
# Rule-challenge records (D-138): the format check and the listing, hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_rule_challenges.py"
