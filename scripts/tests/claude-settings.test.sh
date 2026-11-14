#!/usr/bin/env bash
# .claude/settings.json: hook kept, allow and deny lists present, no bypass mode.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
exec python3 "$root/scripts/tests/test_claude_settings.py"
