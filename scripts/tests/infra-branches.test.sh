#!/usr/bin/env bash
# BRANCH-MERGE: the base merged into a unit's branch and pushed by the live service with the forge's
# key, in a clone of its own; the delivery follows it. Hermetic but for the SQL class, which
# needs TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_branches.py'
