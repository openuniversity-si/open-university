#!/usr/bin/env bash
# F80: the Bash PostToolUse trim hook on synthetic events, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_bash_trim.py"
