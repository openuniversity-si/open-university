#!/usr/bin/env bash
# The fast deploy (DEP8): the alias swap, smoke, rollback, freshness, the autodeploy wiring and the task role's IAM. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_fastdeploy.py'
