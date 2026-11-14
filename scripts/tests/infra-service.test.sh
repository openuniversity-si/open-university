#!/usr/bin/env bash
# The infrastructure's service (engine-infra-service, P3 F1): its migrations at start and its database init step on
# throwaway databases of the toolchain's PostgreSQL (TI1), and its stack and image. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_service.py"
