#!/usr/bin/env bash
# The checkout's core.hooksPath points at .githooks (D-222 (5)). Hermetic: reads only this checkout's git config.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec "${OU_PYTHON:-python3}" "$root/scripts/tests/test_hooks_path.py"
