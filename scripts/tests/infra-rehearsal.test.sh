#!/usr/bin/env bash
# FIRST-JOB-REHEARSED (tower_infra.rehearsal): a job of no one through a real job's whole path, rolled back, beside a live
# dispatcher and a live runner that wait for no lock of it, on throwaway databases (TI1).
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_rehearsal.py"
