#!/usr/bin/env bash
# The registry-driven local check (LR1, D-069): fixture git repos, fake clock. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_local_checks.py'
