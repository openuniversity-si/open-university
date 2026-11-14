#!/usr/bin/env bash
# IMAGE-PREWARM-C: the image-only swap on landing (both pointers in one statement, only to a merge that runs the PR head's
# bundle with two healthy standbys), the ECS tasks' digest and LiveCode, the handover, the retirement off the clock and the
# measures. Hermetic (fake database, ECS, git repositories); the SQL class needs TEST_DATABASE_URL (Postgres) and is skipped
# without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_image_swap.py'
