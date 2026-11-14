#!/usr/bin/env bash
# The merge train (TRAIN-FRONT-FIRST): the front lands first, a red front leaves, an unrelated front costs no new judgment. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_merge_train.py"
