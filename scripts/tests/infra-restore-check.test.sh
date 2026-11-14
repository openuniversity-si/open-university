#!/usr/bin/env bash
# RESTORE-DRILL (tower_infra.restore_check): the reading of a database restored from the backup, read only, and its
# comparison with production's, on throwaway databases (TI1).
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_restore_check.py"
