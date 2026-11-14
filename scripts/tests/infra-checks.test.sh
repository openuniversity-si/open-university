#!/usr/bin/env bash
# CHECK-RUN-AWS: tower/gate asked at the port and posted by the live service with the Origin app's key from Parameter
# Store (the Worker off the path); the gate's client waits for the service's word. Hermetic but for the SQL class, which
# needs TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_checks.py'
