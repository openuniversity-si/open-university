#!/usr/bin/env bash
# The infrastructure's schemas work and log (engine-infra-db, D-306, D-308): the first migration under infra/db and the
# phase-1 acceptance test, on a throwaway database of the toolchain's PostgreSQL (TI1). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_db.py"
