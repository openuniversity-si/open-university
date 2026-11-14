#!/usr/bin/env bash
# No module under scripts/lib writes git data (trees, commits, refs, blobs, tags) through REST; it reads them all. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "$root/scripts/tests/test_no_rest_git_write.py"
