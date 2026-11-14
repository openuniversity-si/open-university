#!/usr/bin/env bash
# TASK-POOLER: the task keeps its connections to the database (tower_infra.pooler): with the real client (psql) through
# the real pool to the toolchain's PostgreSQL, a process lost in the middle of anything leaves nothing, and the one that
# takes its place has its connection at once, with no login (the runner's real TAKE, the service's real dispatch); the
# login the pool makes is RDS's (TLS, the token in clear inside it), before a front that asks exactly that.
# Throwaway databases (TI1); no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_pooler.py"
