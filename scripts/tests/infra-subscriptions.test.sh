#!/usr/bin/env bash
# The log's subscriptions (engine-infra-service, P3 F4): the service's deliverer sends each subscription's events from
# its cursor, through the port on a throwaway database (TI1), with a recording sink. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_subscriptions.py"
