#!/usr/bin/env bash
# PSQL-SESSIONS: the Postgres tests' statements on psql sessions that stay up, each ended by DISCARD ALL; anything psql
# would split goes through `psql -c` as before. The SQL class needs TEST_DATABASE_URL (Postgres).
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_psql.py'
