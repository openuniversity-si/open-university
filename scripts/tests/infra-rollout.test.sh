#!/usr/bin/env bash
# SLOW-PATH-NO-ROLLOUT-WAIT: the service's side of a slow deploy that waits for no rollout: the live service applies the head's
# migrations ahead of its tasks (the runner never rolls after the service) and the port answers the newest one applied.
# Hermetic; the SQL class needs TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_rollout.py'
