#!/usr/bin/env bash
# SWAP-MEASURE: a round of the image swap measured by command (POST /v1/deploy/measure) through the landing's own path:
# the published head's bundle with the round's mark, its successors wanted, the drill of both roles, the readiness
# question, the swap of both pointers once both rehearsed, the round's end at the takeover; the autodeploy gives its
# pointers back after the takeover; scripts/medir's official series by role. Hermetic but for the SQL class, which needs
# TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_swap_measure.py'
