#!/usr/bin/env bash
# SWAP-CPU: what the task's CPU quota holds back from a reserve's word to its first work, said in the swap's record (the
# cgroup's cpu.stat, v2 and v1), the service's gate's first read on its loop's own connection, and the threads of no
# work of the role at a lower priority. Hermetic; no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [[ -z "${TEST_DATABASE_URL:-}" ]]; then
  # shellcheck disable=SC1091  # scripts/cloud/env.sh: the local test database defaults
  source "$root/scripts/cloud/env.sh"
fi
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_swap_cpu.py"
