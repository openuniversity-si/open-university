#!/usr/bin/env bash
# IMAGE-SWAP-TICK: the first work of each role after an image-only swap: the service's first tick on the connection its
# standby kept (no login, one round trip a statement), image_live timed at its first committed claim with its parts, and
# no look of the retired service on the swap's second. Hermetic; the SQL class needs TEST_DATABASE_URL (Postgres) and is
# skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_swap_tick.py'
