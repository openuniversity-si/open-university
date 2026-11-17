#!/usr/bin/env bash
# Retired vendors (D-318): no tracked path or acting line names a retired vendor; only the records keep the past. Hermetic: temp repos.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_retired_vendors*.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$test"
done
