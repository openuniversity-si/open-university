#!/usr/bin/env bash
# env-check's pinned toolchain and early stop (D-027) on fixtures. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_env.py"
