#!/usr/bin/env bash
# The Origin webhook ingress (PORT3): signature check without a database, a durable queue write and 202, and the consumer
# that records each queued delivery once, on a throwaway database (TI1). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_ingress.py"
