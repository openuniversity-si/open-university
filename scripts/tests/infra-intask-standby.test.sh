#!/usr/bin/env bash
# IN-TASK-STANDBY: the standby of a code-only head is a successor process inside the ECS task of its role, held by the
# task's first process (the supervisor): real processes prove its lifecycle (a successor started on a want, promoted by a
# yield, the previous process leaving after its work, SIGTERM forwarded, a successor dismissed, one that dies restarted
# and reported). Hermetic; a class that needs Postgres is skipped without TEST_DATABASE_URL.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_intask_standby.py'
