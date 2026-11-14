#!/usr/bin/env bash
# IMAGE-SWAP-DB-LOAD: no statement of the image-only swap's moment scans the whole log or the work tables (migration 0015's
# indexes). Needs TEST_DATABASE_URL (Postgres); skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_swap_db_load.py'
