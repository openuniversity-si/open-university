#!/usr/bin/env bash
# IMAGE-SWAP-FAILOVER: a promoted standby that dies or hangs never leaves its role without a live process: the live beat of
# the process the pointer names, the ECS task's watchdog that fails the role over, and the handback on SIGTERM.
# Hermetic; the SQL class needs TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_swap_failover.py'
