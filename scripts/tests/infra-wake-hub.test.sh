#!/usr/bin/env bash
# DB-LISTEN-ONE: one connection of each process of the engine listens for all its waiters (wake.Hub): a notification wakes
# the waiters of its channel at once, a lost connection never raises and never spins, and serve and run-container make one
# hub each. Hermetic; the LISTEN/NOTIFY class needs TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_wake_hub.py'
