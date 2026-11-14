#!/usr/bin/env bash
# The deploy classifier (DEP6): real directories to targets. Hermetic, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_deploy_classify.py'
