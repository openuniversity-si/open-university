#!/usr/bin/env bash
# The regenerate merge driver of committed generated files (CENSO-NO-MANIFESTO 3bis) on fixture branches. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$root/scripts/tests/test_merge_regenerate.py"
