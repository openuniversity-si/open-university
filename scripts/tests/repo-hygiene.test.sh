#!/usr/bin/env bash
# Repository hygiene (OU-DECOUPLE F2, D-105): no legacy-domain address in a tracked file, no raster image in git. Hermetic: temp repos.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_repo_hygiene*.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$test"
done
