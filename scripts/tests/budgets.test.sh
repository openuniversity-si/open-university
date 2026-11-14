#!/usr/bin/env bash
# Performance budgets and the measured baseline (B1, D-069 item 14): hermetic, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_budget*.py'
