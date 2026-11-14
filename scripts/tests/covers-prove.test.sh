#!/usr/bin/env bash
# Runs one script test in a throwaway worktree without the files a covers pattern would stop covering: PASS means the pattern can go (D-178). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_covers_prove.py"
