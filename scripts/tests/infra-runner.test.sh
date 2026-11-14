#!/usr/bin/env bash
# The warm runner of the container executor (engine-infra-service, P4 F1): it takes the runs the service's dispatcher
# handed over, runs their command on a checkout with its lease renewed, and ends them, on a throwaway database (TI1),
# with a local fetch, prepare and upload. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_runner.py"
