#!/usr/bin/env bash
# Max-behind-base rule for merging a gated head (BD1): pure decisions against the registered limits. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_merge_behind.py"
