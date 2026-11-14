#!/usr/bin/env bash
# RUNNER-OWN-LOGIN (migration 0019): the runner's login takes, relays, renews and ends runs, says what a runner says
# and hands a pointer back, and is refused everything else, on throwaway databases (TI1).
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_runner_login.py"
