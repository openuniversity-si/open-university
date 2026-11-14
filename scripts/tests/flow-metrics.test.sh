#!/usr/bin/env bash
# Integrated commits and their guards (FLUXO-AMPLO, D-137): a throwaway git repository, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_flow_metrics.py"
