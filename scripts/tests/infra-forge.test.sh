#!/usr/bin/env bash
# The forge executor of the infrastructure (engine-infra-service, P4 F2): Origin through a stub of its CLI, alone and
# through the service's dispatcher on a throwaway database (TI1). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_forge.py"
