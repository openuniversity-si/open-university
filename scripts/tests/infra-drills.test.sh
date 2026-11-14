#!/usr/bin/env bash
# DRILLS: a port Lambda's rollback rehearsed and Spot's placement failure of the runner provoked, by the port's ask and the
# live service's look; on a throwaway database.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_drills.py"
