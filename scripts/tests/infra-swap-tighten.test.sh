#!/usr/bin/env bash
# IMAGE-SWAP-TIGHTEN: the image-only swap from the landing to both roles working, under 1 s: the landing swaps in
# the statement that records it (standby beats as evidence), and image_live with its parts at the first work. Hermetic;
# the SQL class needs TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_swap_tighten.py'
