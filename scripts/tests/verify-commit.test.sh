#!/usr/bin/env bash
# The verifier thread's gate (scripts/verify-commit): the gate's plan judged on the exact commit and published as its
# tower/gate commit status. Hermetic: a fake run answers git, gate-check and gh.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_verify_commit.py"
