#!/usr/bin/env bash
# The merge train's role (lock, drain loop, flag) and the GitHub adapter's train operations. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_train_role.py"
