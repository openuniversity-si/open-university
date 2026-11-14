#!/usr/bin/env bash
# RELOAD-WITHOUT-STANDBY: a code-only landing with no healthy standby pair is loaded in place by the ECS tasks, the runner
# first and then the service, each judged by the other's canary reading; a red one sends them back afresh and the landing
# is the slow path's; both proven, deploy.live_code is written and the build deploys neither the image nor the stacks.
# Hermetic; the SQL class needs TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_reload_nostandby.py'
