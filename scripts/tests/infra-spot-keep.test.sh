#!/usr/bin/env bash
# SPOT-KEEP: at Spot's warning the runner's task keeps taking runs until the task ECS starts in its place is up (the
# handler on a clock of its own; REPLACED on a migrated PostgreSQL; the status's runner lives and medir's gap on the
# real events of 12/11 19:27 UTC). Throwaway databases (TI1); no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_spot_keep.py"
