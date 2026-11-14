#!/usr/bin/env bash
# The decisions-to-premises check on temporary git repositories and on this repository's register at HEAD. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
exec python3 "$root/scripts/tests/test_decision_premises.py"
