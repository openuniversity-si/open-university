#!/usr/bin/env bash
# The gate over the infrastructure (engine-gate-infra, P5 F2): one gate check as a job's command (scripts/gate-check)
# and the adapter that judges a head with the infrastructure's jobs, end to end in shadow on a throwaway database (TI1).
# No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_gate_infra.py"
