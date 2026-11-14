#!/usr/bin/env bash
# IMAGE-SWAP-SERVICE-READY: both roles ready before the image-only swap: the service's standby launches DBOS while it stands
# by and records image_live at its first committed dispatch; the runner's standby wakes on the gate and TAKEs at once.
# Hermetic; the SQL class needs TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_swap_ready.py'
