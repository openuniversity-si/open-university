#!/usr/bin/env bash
# commit-check (D-025) on fixture PRs. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_commit_check.py"
