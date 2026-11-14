#!/usr/bin/env bash
# IMAGE-PREWARM-A: the live image of each role (deploy.live_image_<role>), the standby of a runner or service that is not
# the pointer's image, the swap on the tower_config event and platform.deploy.image_live. Hermetic; the SQL class needs
# TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_live_image.py'
