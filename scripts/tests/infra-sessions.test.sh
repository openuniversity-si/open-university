#!/usr/bin/env bash
# The AI session executor (engine-infra-service, P4 F3): the adapter launches, follows, waits on the quota, resumes and
# ends a session through a fake provider, through the port and the dispatcher on a throwaway database (TI1). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_sessions.py"
