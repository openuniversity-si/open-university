#!/usr/bin/env bash
# The port of the infrastructure (engine-infra-service, P3 F2, D-309): the acceptance test through the port with two
# tenants, on a throwaway database of the toolchain's PostgreSQL (TI1). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_port.py"
