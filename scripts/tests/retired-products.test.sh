#!/usr/bin/env bash
# Retired products (OU-DECOUPLE F5, D-113): no tracked path under a retired root, no acting file naming one. Hermetic: temp repos.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_retired_products*.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$test"
done
