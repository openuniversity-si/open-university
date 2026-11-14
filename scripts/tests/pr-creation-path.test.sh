#!/usr/bin/env bash
# deliver --open is the one way a PR is opened, and it checks the body first (lane 4, D-236; lane-ship until F9). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_pr_creation_path.py"
