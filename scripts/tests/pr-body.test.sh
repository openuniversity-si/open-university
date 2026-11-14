#!/usr/bin/env bash
# The PR body from the branch's commits and four effort fields, so no session types the plan or the footer again (D-208). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_pr_body.py"
