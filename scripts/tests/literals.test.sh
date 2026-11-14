#!/usr/bin/env bash
# The census of unregistered engine literals (LT1, D-068 (6), D-069 item 3): fixture checkouts in a temp dir. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_literal_census*.py'
