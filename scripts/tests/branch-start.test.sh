#!/usr/bin/env bash
# A branch starts from the base in one command: fetch, refuse a dirty tree or a name already on the remote, create from the base (F2, D-210). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_branch_start.py"
