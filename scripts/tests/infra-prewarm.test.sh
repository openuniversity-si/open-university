#!/usr/bin/env bash
# IMAGE-PREWARM-B2: on each unit branch's push the live service makes the head's bundle job and, for a code-only head, one
# standby Fargate task per role; the lifecycle by events (a newer push, a deleted branch, a closed PR, the cap) and
# platform.deploy.standby in the status. Hermetic (a fake database and ECS); the SQL class needs TEST_DATABASE_URL
# (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_prewarm.py'
