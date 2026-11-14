#!/usr/bin/env bash
# DEPLOY-CANARY: the deploy's smoke proves the engine works end to end: one canary job created by the port, dispatched by the
# service, taken and run by the runner, with a verdict that names the stage that never happened.
# Hermetic; the SQL class needs TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_canary.py'
