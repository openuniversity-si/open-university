#!/usr/bin/env bash
# GIT-TOKEN-AUTH: git authenticates to the forge with the minted token in its environment, the credential helper behind it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_git_token.py"
