#!/usr/bin/env bash
# The forge's webhooks into the log (engine-infra-service, P4 F2b): Ed25519 in the standard library against RFC 8032's
# vectors and an independent implementation, and Origin's deliveries through the port on a throwaway database (TI1).
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_webhooks.py"
