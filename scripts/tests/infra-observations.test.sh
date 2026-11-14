#!/usr/bin/env bash
# PR-OBSERVATION: what `pr metadata` reads of a PR, asked at the port and read by the live service with the forge's
# key (the lane's login and reflog off the path). Hermetic but for the SQL class, which
# needs TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_observations.py'
